import hmac
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from vast_inferencer.config import get_settings

_bearer = HTTPBearer(auto_error=False)


async def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Unauthorized")
    expected = get_settings().api_bearer_key.get_secret_value()
    if not hmac.compare_digest(credentials.credentials, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")
