"""HTTP routes — screen metadata (JWT with tenant_id)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mtf.shared.deps import CurrentUser, get_db
from mtf.txn.api.deps import get_screen_caller
from mtf.txn.schemas import ScreenMetadataRead
from mtf.txn.services.screen_metadata import ScreenMetadataService

router = APIRouter(prefix="/screens", tags=["screens"])


def get_screen_metadata_service(db: Session = Depends(get_db)) -> ScreenMetadataService:
    return ScreenMetadataService(db)


@router.get("/{screen_key}", response_model=ScreenMetadataRead)
def get_screen(
    screen_key: str,
    user: CurrentUser = Depends(get_screen_caller),
    service: ScreenMetadataService = Depends(get_screen_metadata_service),
) -> ScreenMetadataRead:
    assert user.tenant_id is not None
    return service.get_screen(user.tenant_id, user.user_id, screen_key)
