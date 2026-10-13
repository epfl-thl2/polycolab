"""Authenticated username selection, separate from identity-provider claims."""

from fastapi import APIRouter, HTTPException, Response

from polycolab.accounts.schemas import UsernameWrite, UserRead
from polycolab.accounts.usernames import UsernameConflict, choose_username
from polycolab.app.dependencies import CurrentUser, RequestTransaction

router = APIRouter(prefix="/api/v1/account", tags=["users"])


@router.put("/username", response_model=UserRead, operation_id="chooseUsername")
def username(
    payload: UsernameWrite, user: CurrentUser, transaction: RequestTransaction, response: Response
) -> UserRead:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        selected = choose_username(transaction, user.id, payload.username)
    except ValueError:
        raise HTTPException(422, "invalid_username") from None
    except UsernameConflict:
        raise HTTPException(409, "username_unavailable") from None
    return UserRead.model_validate(selected)
