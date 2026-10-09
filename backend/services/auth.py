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
        decoded = firebase_auth.verify_id_token(token)
        # Admin SDK returns `uid` (= sub), but be tolerant across versions.
        uid = decoded.get("uid") or decoded.get("user_id") or decoded.get("sub")
        if uid:
            decoded["uid"] = uid
        return decoded
    except Exception:
        return None


def get_owner_uid(user: dict | None) -> str | None:
    """Owner scope for per-user data isolation.

    Authenticated users get their Firebase `uid`; anonymous/guest traffic
    gets None (the shared open-demo namespace). Every new sign-up therefore
    starts with an empty workspace instead of seeing the admin demo data.
    """
    if not user or user.get("anonymous"):
        return None
    uid = user.get("uid")
    return uid or None


def doc_owner(doc: dict | None) -> str | None:
    """Owner stored on a Firestore document (None for legacy/global docs)."""
    if doc is None:
        return None
    return doc.get("owner_uid") or None


def is_visible(doc: dict | None, user: dict | None) -> bool:
    """New users see only their own docs; admin/anonymous keep legacy data.

    - Regular authenticated user: only docs where owner_uid == uid.
    - Admin: own docs + legacy docs (owner_uid missing/None).
    - Anonymous: only legacy/global docs.
    """
    if doc is None:
        return False
    owner = doc_owner(doc)
    if not user or user.get("anonymous"):
        return owner is None
    if user.get("admin"):
        return owner is None or owner == user.get("uid")
    return owner is not None and owner == user.get("uid")


def owner_cache_key(user: dict | None) -> str:
    """Scope search/suggestion caches per owner to avoid cross-user leaks."""
    uid = get_owner_uid(user)
    if not uid:
        return "anon"
    if user.get("admin"):
        return f"admin-{uid}"
    return f"user-{uid}"


async def resolve_user(request: Request) -> dict:
    """Never raises. Anonymous passthrough when auth is not enforced."""
    user = {"uid": None, "email": None, "admin": False, "anonymous": True}
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        claims = _verify_token(header[7:].strip())
        if claims:
            user = {
                "uid": claims.get("uid") or claims.get("user_id") or claims.get("sub"),
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
