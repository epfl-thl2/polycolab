"""Describe API authentication from the dependencies that enforce it."""

from fastapi.dependencies.models import Dependant
from fastapi.routing import RouteContext

from polycolab.accounts.authentication import current_principal
from polycolab.agents.routes.keys import required_key
from polycolab.app.access import research_access
from polycolab.app.dependencies import authenticated_actor, authenticated_user


def policy(route: RouteContext) -> str:
    def calls(dependency: Dependant) -> list[object]:
        return [
            dependency.call,
            *(call for child in dependency.dependencies for call in calls(child)),
        ]

    dependencies = calls(route.dependant)
    if any(
        call in dependencies
        for call in [authenticated_actor, authenticated_user, current_principal]
    ):
        return "human"
    if required_key in dependencies:
        return "agent"
    if research_access in dependencies:
        return "shared"
    return "anonymous"
