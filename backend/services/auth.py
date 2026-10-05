"""Firebase Authentication enforcement.

Modes:
- Open (REQUIRE_AUTH=false, default): the evaluator demo link works with no
  sign-in. Requests without a token resolve to an anonymous user.
- Enforced (REQUIRE_AUTH=true): every API call needs a valid Firebase ID
  token in the `Authorization: Bearer <token>` header.

Attach `resolve_user` to routers so handlers can read request.state.user.
Use `require_admin` on sensitive endpoints (e.g. source deletion).
"""

from fastapi import Depends, HTTPException, Request
from firebase_admin import auth as firebase_auth

from backend.config import initialize_firebase, settings


def _verify_token(token: str) -> dict | None:
    try:
        initialize_firebase()  # no-op after first call; no network on its own
        return firebase_auth.verify_id_token(token)
    except Exception:
        return None


async def resolve_user(request: Request) -> dict:
    """Never raises. Anonymous passthrough when auth is not enforced."""
    user = {"uid": None, "email": None, "admin": False, "anonymous": True}
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        claims = _verify_token(header[7:].strip())
        if claims:
            user = {
                "uid": claims.get("uid"),
                "email": claims.get("email"),
                "admin": bool(claims.get("admin")),
                "anonymous": False,
            }
    request.state.user = user
    return user


async def require_user(request: Request) -> dict:
    """401 unless a valid ID token is present (only enforced when configured)."""
    user = await resolve_user(request)
    if settings.require_auth and user["anonymous"]:
        raise HTTPException(status_code=401, detail="Sign-in required")
    return user


async def require_admin(user: dict = Depends(require_user)) -> dict:
    """403 unless the caller carries the admin custom claim (when enforced)."""
    if settings.require_auth and not user.get("admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
