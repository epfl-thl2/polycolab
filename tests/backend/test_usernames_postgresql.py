from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, Table, select
from sqlalchemy.engine import Engine
from test_public_external_agents import headers

from polycolab.accounts.authentication import MappingIdentityVerifier
from polycolab.app.application import create_app
from polycolab.entities.time import utc_now
from polycolab.platform.config import Settings


def test_username_migration_and_concurrent_claims_on_postgresql(
    pg_schema: tuple[Engine, Config, str], identity_verifier: MappingIdentityVerifier
) -> None:
    engine, config, url = pg_schema
    command.upgrade(config, "20261012_projects")
    account_id, user_id = uuid4(), uuid4()
    metadata = MetaData()
    users = Table("users", metadata, autoload_with=engine)
    accounts = Table("local_accounts", metadata, autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(
            accounts.insert().values(
                id=account_id,
                username="retained-name",
                password_digest="historical-verifier",
                display_name="Retained",
                is_admin=False,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        connection.execute(
            users.insert().values(
                id=user_id,
                issuer="polycolab-local",
                subject=str(account_id),
                display_name="Retained",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    command.upgrade(config, "head")
    upgraded = Table("users", MetaData(), autoload_with=engine)
    with engine.connect() as connection:
        row = connection.execute(select(upgraded).where(upgraded.c.id == user_id)).mappings().one()
        assert row["username"] == "retained-name" and row["subject"] == str(account_id)
    app = create_app(
        Settings(database_url=url, web_dist_dir="/missing-username-web"), identity_verifier
    )
    try:
        with TestClient(app) as client:
            for token in ["owner", "contributor"]:
                assert client.get("/api/v1/users/me", headers=headers(token)).status_code == 200
            assert (
                client.put(
                    "/api/v1/account/username",
                    headers=headers(),
                    json={"username": "retained-name"},
                ).status_code
                == 409
            )

            def claim(token: str) -> int:
                result = client.put(
                    "/api/v1/account/username",
                    headers=headers(token),
                    json={"username": "race-name"},
                ).status_code
                return int(result)

            with ThreadPoolExecutor(max_workers=2) as executor:
                assert sorted(executor.map(claim, ["owner", "contributor"])) == [200, 409]
            names = [
                client.get("/api/v1/users/me", headers=headers(token)).json()["username"]
                for token in ["owner", "contributor"]
            ]
            assert names.count("race-name") == 1
            with cast(Any, app).state.session_factory() as session:
                from polycolab.db.stores.accounts import SqlAccountStore

                retained = SqlAccountStore(session).user(user_id)
                assert retained is not None and retained.username == "retained-name"
    finally:
        app.state.engine.dispose()
