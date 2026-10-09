"""Public execution/recovery availability, without actor permissions or private settings."""

from fastapi import APIRouter, Request, Response

from polycolab.app.schemas import ApiModel
from polycolab.platform.config import AuthMode, Settings


class ApplicationConfiguration(ApiModel):
    agent_execution: bool
    verification_submission: bool
    verification_execution: bool
    email_recovery: bool


def application_configuration(settings: Settings) -> ApplicationConfiguration:
    return ApplicationConfiguration(
        agent_execution=settings.feature_agent_execution_enabled,
        verification_submission=settings.feature_verification_submission_enabled,
        verification_execution=settings.feature_verification_execution_enabled,
        email_recovery=(
            settings.auth_mode is AuthMode.LOCAL
            and settings.smtp_host is not None
            and settings.smtp_from_address is not None
            and settings.public_app_origin is not None
        ),
    )


router = APIRouter()


@router.get("/api/v1/config", operation_id="getApplicationConfiguration", tags=["configuration"])
def get_configuration(request: Request, response: Response) -> ApplicationConfiguration:
    response.headers["Cache-Control"] = "no-store"
    return application_configuration(request.app.state.settings)
