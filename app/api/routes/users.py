"""User management endpoints for home zone configuration."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models import User
from app.db.session import get_session

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UserHomeZoneUpdate(BaseModel):
    """Schema for updating user's home zone."""

    home_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    home_lon: Optional[float] = Field(default=None, ge=-180, le=180)


class UserResponse(BaseModel):
    """User response schema (coordinates intentionally excluded for privacy)."""

    id: str
    name: str
    has_home_zone: bool


@router.put("/{user_id}/home-zone", response_model=UserResponse)
async def set_home_zone(
    user_id: str,
    data: UserHomeZoneUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    """
    Set or update a user's home zone coordinates.

    These coordinates are used for privacy filtering.
    Once set, any pings within 50m of this location will have
    their coordinates nullified before storage.

    Note: For security, this endpoint does NOT return the actual
    home coordinates in the response.
    """
    result = await session.exec(select(User).where(User.id == user_id))
    user = result.first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.home_lat = data.home_lat
    user.home_lon = data.home_lon
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return UserResponse(
        id=user.id,
        name=user.name,
        has_home_zone=user.home_lat is not None and user.home_lon is not None,
    )


@router.delete("/{user_id}/home-zone", response_model=UserResponse)
async def clear_home_zone(
    user_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    """Clear a user's home zone (disable privacy filtering)."""
    result = await session.exec(select(User).where(User.id == user_id))
    user = result.first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.home_lat = None
    user.home_lon = None
    session.add(user)
    await session.commit()
    await session.refresh(user)

    return UserResponse(
        id=user.id,
        name=user.name,
        has_home_zone=False,
    )
