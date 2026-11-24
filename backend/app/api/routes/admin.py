"""Administrator user-management endpoints.

Every route requires an authenticated, approved administrator. Mutations are
audited by the service layer inside the same transaction as the profile change.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from ...core.db import DB_ERRORS, Database
from ...models.schemas import (
    AdminAssetList,
    AdminAssetOut,
    AdminJobList,
    AdminJobOut,
    AdminUserList,
    AppRole,
    AssetStatus,
    JobStatus,
    ProfileOut,
    RoleUpdate,
)
from ...services import admin_inventory, profiles
from ...services.profiles import ConflictError, MAX_PAGE_SIZE
from ...services.storage import Storage
from ..deps import get_db, get_storage, require_admin
from ..errors import ApiError

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _unavailable() -> ApiError:
    return ApiError(
        503,
        "service_unavailable",
        "The service is temporarily unavailable.",
    )


def _not_found() -> ApiError:
    return ApiError(404, "user_not_found", "User not found.")


@router.get("/users", response_model=AdminUserList)
async def list_users(
    search: str | None = Query(default=None, max_length=200),
    approved: bool | None = Query(default=None),
    role: AppRole | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    admin: ProfileOut = Depends(require_admin),
    db: Database | None = Depends(get_db),
) -> AdminUserList:
    """List and filter user profiles. ``limit`` is clamped to 1..200."""
    if db is None:
        raise _unavailable()
    clamped_limit = max(1, min(MAX_PAGE_SIZE, int(limit)))
    clamped_offset = max(0, int(offset))
    try:
        rows, total = await profiles.list_profiles(
            db,
            search=search,
            approved=approved,
            role=role,
            limit=clamped_limit,
            offset=clamped_offset,
        )
    except DB_ERRORS as exc:
        raise _unavailable() from exc

    return AdminUserList(
        items=[ProfileOut.model_validate(row) for row in rows],
        total=total,
        limit=clamped_limit,
        offset=clamped_offset,
    )


@router.post("/users/{user_id}/approve", response_model=ProfileOut)
async def approve_user(
    user_id: UUID,
    admin: ProfileOut = Depends(require_admin),
    db: Database | None = Depends(get_db),
) -> ProfileOut:
    if db is None:
        raise _unavailable()
    try:
        row = await profiles.approve_profile(db, user_id, admin.id)
    except DB_ERRORS as exc:
        raise _unavailable() from exc
    if row is None:
        raise _not_found()
    return ProfileOut.model_validate(row)


@router.post("/users/{user_id}/revoke", response_model=ProfileOut)
async def revoke_user(
    user_id: UUID,
    admin: ProfileOut = Depends(require_admin),
    db: Database | None = Depends(get_db),
) -> ProfileOut:
    if db is None:
        raise _unavailable()
    try:
        row = await profiles.revoke_profile(db, user_id, admin.id)
    except ConflictError as exc:
        raise ApiError(409, exc.code, exc.message) from exc
    except DB_ERRORS as exc:
        raise _unavailable() from exc
    if row is None:
        raise _not_found()
    return ProfileOut.model_validate(row)


@router.post("/users/{user_id}/role", response_model=ProfileOut)
async def set_user_role(
    user_id: UUID,
    payload: RoleUpdate,
    admin: ProfileOut = Depends(require_admin),
    db: Database | None = Depends(get_db),
) -> ProfileOut:
    if db is None:
        raise _unavailable()
    try:
        row = await profiles.set_profile_role(db, user_id, payload.app_role, admin.id)
    except ConflictError as exc:
        raise ApiError(409, exc.code, exc.message) from exc
    except ValueError as exc:
        raise ApiError(400, "invalid_role", "Invalid application role.") from exc
    except DB_ERRORS as exc:
        raise _unavailable() from exc
    if row is None:
        raise _not_found()
    return ProfileOut.model_validate(row)


def _asset_not_found() -> ApiError:
    return ApiError(404, "asset_not_found", "Asset not found.")


@router.get("/jobs", response_model=AdminJobList)
async def list_jobs(
    user_id: UUID | None = Query(default=None),
    status: JobStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    admin: ProfileOut = Depends(require_admin),
    db: Database | None = Depends(get_db),
) -> AdminJobList:
    """List all users' jobs, newest first. ``limit`` is clamped to 1..200."""
    if db is None:
        raise _unavailable()
    clamped_limit = max(1, min(MAX_PAGE_SIZE, int(limit)))
    clamped_offset = max(0, int(offset))
    try:
        rows, total = await admin_inventory.list_jobs(
            db,
            user_id=user_id,
            status=status,
            search=search,
            limit=clamped_limit,
            offset=clamped_offset,
        )
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "Invalid job filter.") from exc
    except DB_ERRORS as exc:
        raise _unavailable() from exc
    return AdminJobList(
        items=[AdminJobOut.model_validate(row) for row in rows],
        total=total,
        limit=clamped_limit,
        offset=clamped_offset,
    )


@router.get("/assets", response_model=AdminAssetList)
async def list_assets(
    status: AssetStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    admin: ProfileOut = Depends(require_admin),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> AdminAssetList:
    """List the global asset cache with usage counts and free disk space."""
    if db is None:
        raise _unavailable()
    clamped_limit = max(1, min(MAX_PAGE_SIZE, int(limit)))
    clamped_offset = max(0, int(offset))
    try:
        rows, total = await admin_inventory.list_assets(
            db,
            status=status,
            search=search,
            limit=clamped_limit,
            offset=clamped_offset,
        )
        free_bytes = storage.free_bytes()
    except ValueError as exc:
        raise ApiError(400, "invalid_request", "Invalid asset filter.") from exc
    except DB_ERRORS as exc:
        raise _unavailable() from exc
    return AdminAssetList(
        items=[AdminAssetOut.model_validate(row) for row in rows],
        total=total,
        limit=clamped_limit,
        offset=clamped_offset,
        disk_free_bytes=free_bytes,
    )


@router.delete(
    "/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_asset(
    asset_id: UUID,
    admin: ProfileOut = Depends(require_admin),
    db: Database | None = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """Delete a global asset when no active job still references it."""
    if db is None:
        raise _unavailable()
    try:
        deleted = await admin_inventory.delete_asset(
            db, storage, asset_id, admin.id
        )
    except ConflictError as exc:
        raise ApiError(409, exc.code, exc.message) from exc
    except ValueError as exc:
        raise _asset_not_found() from exc
    except DB_ERRORS as exc:
        raise _unavailable() from exc
    if deleted is None:
        raise _asset_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
