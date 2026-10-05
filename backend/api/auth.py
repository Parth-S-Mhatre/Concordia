"""Public client config + identity endpoint (no secrets served)."""

from fastapi import APIRouter, Depends

from backend.config import settings
from backend.services.auth import require_user

router = APIRouter()


@router.get("/config")
async def get_public_config():
    """Non-secret Firebase client config + whether sign-in is enforced."""
    return {
        "projectId": settings.firebase_project_id,
        "apiKey": settings.firebase_api_key,
        "authDomain": settings.firebase_auth_domain
        or (f"{settings.firebase_project_id}.firebaseapp.com" if settings.firebase_project_id else ""),
        "requireAuth": settings.require_auth,
        "demoAdminEmail": settings.demo_admin_email,
    }


@router.get("/me")
async def get_me(user: dict = Depends(require_user)):
    """Who am I (drives the frontend user badge / admin tag)."""
    return user
