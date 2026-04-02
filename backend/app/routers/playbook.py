"""Playbook router — placeholder stubs.

Backlog: full playbook/reflection pipeline.
Phase 4 of the roadmap. Currently no playbook model exists.
These stubs prevent FE from throwing 404 errors on playbook-related calls.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/v1/playbook", tags=["Playbook"])


def _not_implemented():
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Playbook not yet implemented. This feature is planned for Phase 4.",
    )


@router.get("/overview")
async def get_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get playbook overview. Placeholder stub."""
    _ = db
    _ = current_user
    _not_implemented()


@router.get("/bullets")
async def list_bullets(
    status: str | None = None,
    bullet_type: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List playbook bullets. Placeholder stub."""
    _ = status
    _ = bullet_type
    _ = limit
    _ = db
    _ = current_user
    _not_implemented()


@router.post("/bullets/{bullet_id}/archive")
async def archive_bullet(
    bullet_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Archive a playbook bullet. Placeholder stub."""
    _ = bullet_id
    _ = db
    _ = current_user
    _not_implemented()


@router.get("/candidates")
async def list_candidates(
    status: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List reflection candidates. Placeholder stub."""
    _ = status
    _ = limit
    _ = db
    _ = current_user
    _not_implemented()


@router.post("/candidates/generate")
async def generate_candidates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate reflection candidates from feedback events. Placeholder stub."""
    _ = db
    _ = current_user
    _not_implemented()


@router.post("/candidates/{candidate_id}/promote")
async def promote_candidate(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Promote a reflection candidate to a playbook bullet. Placeholder stub."""
    _ = candidate_id
    _ = db
    _ = current_user
    _not_implemented()


@router.post("/candidates/{candidate_id}/reject")
async def reject_candidate(
    candidate_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reject a reflection candidate. Placeholder stub."""
    _ = candidate_id
    _ = db
    _ = current_user
    _not_implemented()


@router.get("/warmup-preview")
async def get_warmup_preview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get warmup data preview. Placeholder stub."""
    _ = db
    _ = current_user
    _not_implemented()
