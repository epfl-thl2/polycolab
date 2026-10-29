"""Describe API authentication from the dependencies that enforce it."""

from fastapi.dependencies.models import Dependant
from fastapi.routing import RouteContext

from polycolab.accounts.authentication import current_principal
from polycolab.app.access import resource_access
from polycolab.app.dependencies import authenticated_actor, authenticated_user
from polycolab.projects.file_access import file_access


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
    if file_access in dependencies:
        return "shared_authenticated"
    if resource_access in dependencies:
        return "shared"
    return "anonymous"
