"""Operator-managed model catalog; public choices never include provider secrets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from polycolab.entities.time import utc_now

if TYPE_CHECKING:
    from polycolab.db.models import SqlProviderConnection
    from polycolab.execution.limits import ExecutionLimits
    from polycolab.model_gateway.credentials import KeyWrapper


class CatalogProvider(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_url: str = Field(min_length=8, max_length=2048)
    api_key_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    wire_api: Literal["chat_completions", "responses"] = "chat_completions"
    api_key: SecretStr = Field(default=SecretStr(""), exclude=True, repr=False)


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    label: str = Field(min_length=1, max_length=200)
    provider: str
    model: str = Field(min_length=1, max_length=500)
    uses: list[Literal["research_helper", "project_chat"]] = Field(min_length=1)
    harnesses: list[Literal["platform", "codex"]] = Field(default=["platform"])
    max_output_tokens: int = Field(default=4096, ge=1, le=100_000)
    input_microusd_per_million_tokens: int = Field(ge=0)
    output_microusd_per_million_tokens: int = Field(ge=0)

    @property
    def connection_id(self) -> UUID:
        return uuid5(NAMESPACE_URL, "https://polycolab.com/platform-model/" + self.id)


class CatalogDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    research_helper: str | None = None
    project_chat: str | None = None


class ModelCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    providers: dict[str, CatalogProvider] = Field(default_factory=dict)
    models: list[CatalogModel] = Field(default_factory=list)
    defaults: CatalogDefaults = Field(default_factory=CatalogDefaults)
    daily_budget_microusd: int = Field(default=10_000_000, ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def references(self) -> Self:
        by_id = {model.id: model for model in self.models}
        if len(by_id) != len(self.models):
            raise ValueError("duplicate platform model ID")
        for model in self.models:
            if model.provider not in self.providers:
                raise ValueError("unknown catalog provider")
            if (
                "codex" in model.harnesses
                and self.providers[model.provider].wire_api != "responses"
            ):
                raise ValueError("Codex requires the Responses protocol")
            if "project_chat" in model.uses and not model.harnesses:
                raise ValueError("project chat models need a harness")
        for use, identifier in self.defaults.model_dump().items():
            if identifier is not None and (
                identifier not in by_id or use not in by_id[identifier].uses
            ):
                raise ValueError("catalog default must name a model enabled for that use")
        return self

    def default_model(self, use: Literal["research_helper", "project_chat"]) -> CatalogModel | None:
        identifier = getattr(self.defaults, use)
        return next((model for model in self.models if model.id == identifier), None)


def load_catalog(path: str) -> ModelCatalog:
    # Never include YAML or validation input in startup errors: configuration may be sensitive.
    try:
        data = yaml.safe_load(Path(path).read_text())
        if not isinstance(data, dict):
            raise ValueError
        if any("api_key" in provider for provider in data.get("providers", {}).values()):
            raise ValueError
        catalog = ModelCatalog.model_validate(data)
        from polycolab.model_gateway.transport import parse_base_url

        providers = {}
        for name, provider in catalog.providers.items():
            if parse_base_url(provider.base_url)[3] != "https":
                raise ValueError
            secret = os.environ.get(provider.api_key_env, "").strip()
            if not secret:
                raise ValueError
            providers[name] = provider.model_copy(update={"api_key": SecretStr(secret)})
        return catalog.model_copy(update={"providers": providers})
    except Exception:
        raise ValueError(
            "invalid model catalog or missing provider credential environment variable"
        ) from None


def sync_catalog(session: Session, catalog: ModelCatalog, wrapper: KeyWrapper) -> None:
    """Snapshot routing and encrypted credentials, preserving stable run references."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from polycolab.db.models import SqlProviderConnection
    from polycolab.model_gateway.credentials import (
        EncryptedCredential,
        credential_context,
        decrypt_credential,
        encrypt_credential,
    )

    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    active_ids = set()
    for model in catalog.models:
        if "project_chat" not in model.uses:
            continue
        active_ids.add(model.id)
        provider = catalog.providers[model.provider]
        context = credential_context(
            user_id=model.connection_id, provider_connection_id=model.connection_id
        )
        encrypted = encrypt_credential(
            wrapper, context=context, secret=provider.api_key.get_secret_value()
        )
        values = dict(
            id=model.connection_id,
            user_id=None,
            platform_model_id=model.id,
            display_name=model.label,
            base_url=provider.base_url.rstrip("/"),
            model_id=model.model,
            wire_api=provider.wire_api,
            credential_version=1,
            encrypted_credential=encrypted.ciphertext,
            wrapped_data_key=encrypted.wrapped_key,
            encryption_key_version=encrypted.key_version,
            platform_config={
                **model.model_dump(),
                "daily_budget_microusd": catalog.daily_budget_microusd,
            },
        )
        session.execute(
            insert(SqlProviderConnection)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["id"])
        )
        connection = session.scalar(
            select(SqlProviderConnection)
            .where(SqlProviderConnection.id == model.connection_id)
            .with_for_update()
        )
        assert (
            connection is not None
            and connection.platform_model_id == model.id
            and connection.user_id is None
        )
        old_secret = (
            ""
            if connection.deleted_at is not None
            else decrypt_credential(
                wrapper,
                context=context,
                encrypted=EncryptedCredential(
                    connection.encrypted_credential,
                    connection.wrapped_data_key,
                    connection.encryption_key_version,
                ),
            )
        )
        changed = (
            connection.deleted_at is not None
            or old_secret != provider.api_key.get_secret_value()
            or any(
                getattr(connection, key) != values[key]
                for key in ("base_url", "model_id", "wire_api", "platform_config")
            )
        )
        if changed:
            connection.credential_version += 1
            for key in (
                "base_url",
                "model_id",
                "wire_api",
                "platform_config",
                "encrypted_credential",
                "wrapped_data_key",
                "encryption_key_version",
            ):
                setattr(connection, key, values[key])
        connection.display_name = model.label
        connection.deleted_at = None
    for connection in session.scalars(
        select(SqlProviderConnection)
        .where(
            SqlProviderConnection.platform_model_id.is_not(None),
            SqlProviderConnection.deleted_at.is_(None),
        )
        .with_for_update()
    ):
        if connection.platform_model_id not in active_ids:
            connection.deleted_at = utc_now()
            connection.credential_version += 1
            connection.encrypted_credential = b""
            connection.wrapped_data_key = b""
    session.commit()


def reserve_budget(session: Session, *, cost: int, limit: int) -> None:
    """Conservative daily reservation, including failures and ambiguous provider I/O."""
    from datetime import UTC, datetime

    from sqlalchemy import update
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    from polycolab.db.models import SqlExecutionRateWindow
    from polycolab.execution.limits import ExecutionLimitExceeded

    now = utc_now()
    day = datetime(now.year, now.month, now.day, tzinfo=UTC)
    scope = dict(scope="platform_budget", scope_id=UUID(int=0), window_started_at=day)
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    session.execute(
        insert(SqlExecutionRateWindow).values(**scope, count=0).on_conflict_do_nothing()
    )
    statement = (
        update(SqlExecutionRateWindow)
        .where(
            SqlExecutionRateWindow.scope == scope["scope"],
            SqlExecutionRateWindow.scope_id == scope["scope_id"],
            SqlExecutionRateWindow.window_started_at == day,
            SqlExecutionRateWindow.count <= limit - cost,
        )
        .values(count=SqlExecutionRateWindow.count + cost)
        .returning(SqlExecutionRateWindow.id)
    )
    if session.scalar(statement) is None:
        raise ExecutionLimitExceeded(
            "platform_daily_budget_exceeded",
            retry_after_seconds=86400 - (now.hour * 3600 + now.minute * 60 + now.second),
        )


def apply_run_policy(
    session: Session,
    connection: SqlProviderConnection,
    harness: str,
    runtime_spec: dict[str, object] | None,
    limits: ExecutionLimits | None,
) -> dict[str, object] | None:
    from polycolab.agents.conversations import ConversationStateError
    from polycolab.agents.runtime.spec import RuntimeSpec

    assert connection.platform_config is not None
    data = connection.platform_config
    model = CatalogModel.model_validate(
        {key: value for key, value in data.items() if key != "daily_budget_microusd"}
    )
    if harness not in model.harnesses or (harness == "codex" and runtime_spec is None):
        raise ConversationStateError("model_harness_incompatible")
    if runtime_spec is not None:
        spec = RuntimeSpec.model_validate(runtime_spec).model_copy(
            update={
                "max_output_tokens": min(
                    int(str(runtime_spec["max_output_tokens"])), model.max_output_tokens
                ),
                "input_microusd_per_million_tokens": model.input_microusd_per_million_tokens,
                "output_microusd_per_million_tokens": model.output_microusd_per_million_tokens,
            }
        )
        cost = spec.round_cost_microusd * spec.max_model_requests * spec.max_attempts
        runtime_spec = spec.model_dump(mode="json")
    else:
        if connection.wire_api != "chat_completions":
            raise ConversationStateError("provider_protocol_incompatible")
        if limits is None:
            raise ConversationStateError("platform_model_limits_required")
        # Global gateway ceilings conservatively bound legacy worker reservations.
        cost = limits.run_cost_microusd
    reserve_budget(session, cost=cost, limit=int(str(data["daily_budget_microusd"])))
    return runtime_spec


def connection_enabled(session: Session, connection: SqlProviderConnection) -> bool:
    """An omitted catalog disables shared inference even before storage synchronization."""
    return connection.platform_model_id is None or connection.platform_model_id in session.info.get(
        "platform_model_ids", ()
    )
