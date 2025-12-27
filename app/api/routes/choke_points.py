"""Choke point management endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models import ChokePoint
from app.db.session import get_session

router = APIRouter(prefix="/api/v1/choke-points", tags=["choke-points"])


class ChokePointCreate(BaseModel):
    """Schema for creating a choke point."""

    name: str = Field(..., min_length=1)
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    radius_m: float = Field(default=50.0, ge=1)
    category: Optional[str] = None


class ChokePointResponse(BaseModel):
    """Schema for choke point response."""

    id: int
    name: str
    lat: float
    lon: float
    radius_m: float
    category: Optional[str]


@router.post("", response_model=ChokePointResponse, status_code=status.HTTP_201_CREATED)
async def create_choke_point(
    data: ChokePointCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ChokePointResponse:
    """Create a new choke point for proximity tracking."""
    choke_point = ChokePoint(
        name=data.name,
        lat=data.lat,
        lon=data.lon,
        radius_m=data.radius_m,
        category=data.category,
    )
    session.add(choke_point)
    await session.commit()
    await session.refresh(choke_point)

    return ChokePointResponse(
        id=choke_point.id,
        name=choke_point.name,
        lat=choke_point.lat,
        lon=choke_point.lon,
        radius_m=choke_point.radius_m,
        category=choke_point.category,
    )


@router.get("", response_model=list[ChokePointResponse])
async def list_choke_points(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ChokePointResponse]:
    """List all choke points."""
    result = await session.exec(select(ChokePoint))
    points = result.all()

    return [
        ChokePointResponse(
            id=p.id,
            name=p.name,
            lat=p.lat,
            lon=p.lon,
            radius_m=p.radius_m,
            category=p.category,
        )
        for p in points
    ]


@router.delete("/{choke_point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_choke_point(
    choke_point_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete a choke point."""
    result = await session.exec(
        select(ChokePoint).where(ChokePoint.id == choke_point_id)
    )
    choke_point = result.first()

    if not choke_point:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Choke point not found",
        )

    await session.delete(choke_point)
    await session.commit()
