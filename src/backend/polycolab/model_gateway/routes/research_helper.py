"""Human-only, project-independent research helper. No transcripts are persisted."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, model_validator

from polycolab.app.dependencies import CurrentUser, DbSession
from polycolab.app.schemas import ApiModel, RequestModel
from polycolab.entities.time import utc_now
from polycolab.execution.limits import enforce_research_helper_limit
from polycolab.model_gateway.research_helper import ResearchProvider, answer
from polycolab.model_gateway.service import ProviderFailure
from polycolab.model_gateway.transport import ProviderTransportError


class ResearchHelperMessage(RequestModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=32_000)


class ResearchHelperRequest(RequestModel):
    model_id: str | None = Field(default=None, max_length=64)
    messages: list[ResearchHelperMessage] = Field(min_length=1, max_length=31)

    @model_validator(mode="after")
    def bounded_conversation(self) -> ResearchHelperRequest:
        if len(self.messages) % 2 != 1:
            raise ValueError("conversation must end with a user question")
        for index, message in enumerate(self.messages):
            if (
                message.role != ("user" if index % 2 == 0 else "assistant")
                or not message.content.strip()
            ):
                raise ValueError("expected alternating user and assistant messages")
        if sum(len(message.content.encode("utf-8")) for message in self.messages) > 48_000:
            raise ValueError("conversation is too long; start a new chat")
        return self


class ResearchHelperReply(ApiModel):
    content: str


router = APIRouter()


@router.post(
    "/api/v1/research-helper/messages", operation_id="askResearchHelper", tags=["research-helper"]
)
def ask(
    payload: ResearchHelperRequest,
    request: Request,
    response: Response,
    db: DbSession,
    user: CurrentUser,
) -> ResearchHelperReply:
    settings = request.app.state.settings
    if not settings.research_helper_available:
        raise HTTPException(503, "research_helper_unavailable")
    catalog = settings.model_catalog
    selected = (
        next(
            (
                model
                for model in catalog.models
                if model.id == payload.model_id and "research_helper" in model.uses
            ),
            None,
        )
        if payload.model_id
        else catalog.default_model("research_helper")
    )
    if payload.model_id and selected is None:
        raise HTTPException(422, "platform_model_unavailable")
    if selected is not None:
        from polycolab.model_gateway.catalog import reserve_budget

        configured = catalog.providers[selected.provider]
        provider = ResearchProvider(
            base_url=configured.base_url,
            model=selected.model,
            wire_api=configured.wire_api,
            api_key=configured.api_key,
            max_output_tokens=min(2048, selected.max_output_tokens),
        )
        input_bound = (
            sum(len(message.content.encode("utf-8")) for message in payload.messages) + 8192
        )
        cost = (
            input_bound * selected.input_microusd_per_million_tokens
            + provider.max_output_tokens * selected.output_microusd_per_million_tokens
            + 999_999
        ) // 1_000_000
        reserve_budget(db, cost=cost, limit=catalog.daily_budget_microusd)
    else:
        provider = ResearchProvider(
            base_url=settings.research_helper_base_url,
            model=settings.research_helper_model,
            wire_api=settings.research_helper_wire_api,
            api_key=settings.research_helper_api_key,
        )
    enforce_research_helper_limit(
        db,
        user_id=user.id,
        user_limit=settings.research_helper_requests_per_minute,
        global_limit=settings.research_helper_global_requests_per_minute,
        now=utc_now(),
    )
    # Commit admission before external I/O, including failures with uncertain billing.
    db.commit()
    try:
        content = answer(
            provider,
            request.app.state.research_helper_transport,
            [message.model_dump() for message in payload.messages],
        )
    except ProviderTransportError, ProviderFailure:
        raise HTTPException(502, "research_helper_provider_unavailable") from None
    response.headers["Cache-Control"] = "no-store"
    return ResearchHelperReply(content=content)
