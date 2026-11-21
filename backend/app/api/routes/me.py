"""Current-user identity endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ...models.schemas import MeOut, ProfileOut
from ..deps import get_current_profile

router = APIRouter(tags=["me"])


@router.get("/api/me", response_model=MeOut)
async def me(profile: ProfileOut = Depends(get_current_profile)) -> ProfileOut:
    """Return the caller's profile. Pending users are allowed here."""
    return profile
