from typing import NoReturn

from fastapi import HTTPException

from vast_inferencer.errors import ConflictError, NotFoundError, PublishFailedError


def raise_mapped(exc: Exception) -> NoReturn:
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=404, detail=exc.detail) from None
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail=exc.detail) from None
    if isinstance(exc, PublishFailedError):
        raise HTTPException(status_code=502, detail="Failed to queue generation") from None
    raise exc
