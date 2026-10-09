from fastapi import APIRouter, HTTPException, Request
from typing import List

from backend.config import db, COLLECTION_RECORDS
from backend.models.schemas import SearchRequest, SearchResponse, EnrichmentStep
from backend.services.cache import cache_get, cache_set
from backend.services.auth import get_owner_uid, is_visible, owner_cache_key
from backend.services.enrichment import progressive_enrichment
from backend.services.fuzzy import fuzzy_candidates
from backend.services.matching import find_matching_records


router = APIRouter()


@router.post("", response_model=SearchResponse)
async def search_entity(payload: SearchRequest, request: Request):
    """Search for an entity using progressive enrichment (cached, §21)."""
    user = getattr(request.state, "user", {"uid": None, "email": None, "admin": False, "anonymous": True})
    if not payload.query or not payload.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    query = payload.query.strip()
    scope = owner_cache_key(user)
    cache_key = f"search:{scope}:{query.lower()}:{payload.limit}"
    cached = cache_get(cache_key)
    if cached:
        return SearchResponse(**cached)

    # Perform progressive enrichment (owner-scoped: fresh users see no admin data)
    result = await progressive_enrichment(query, fuzzy=True, user=user)

    if not result:
        return SearchResponse(
            entity=None,
            sources=[],
            enrichment_steps=[],
            matched_records_count=0,
        )

    entity, steps, sources = result

    response = SearchResponse(
        entity=entity,
        sources=sources,
        enrichment_steps=steps,
        matched_records_count=len(entity.record_ids) if entity.record_ids else 0,
    )
    cache_set(cache_key, response.model_dump(), ttl_seconds=300)
    return response


@router.get("/suggestions")
async def get_search_suggestions(request: Request, q: str = "", limit: int = 10):
    """Get search suggestions based on indexed identifiers (cached)."""
    user = getattr(request.state, "user", {"uid": None, "email": None, "admin": False, "anonymous": True})
    if not q or len(q) < 2:
        return {"suggestions": []}

    scope = owner_cache_key(user)
    cache_key = f"suggest:{scope}:{q.lower()}:{limit}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    suggestions = []
    q_lower = q.lower()
    owner_uid = get_owner_uid(user)

    # Owner-scoped suggestions: scan the caller's own records so a new
    # user's empty workspace yields no admin identifiers.
    if owner_uid:
        try:
            seen = set()
            for doc in db.collection(COLLECTION_RECORDS).stream():
                data = doc.to_dict()
                if not is_visible(data, user):
                    continue
                norm = data.get("normalized_data") or {}
                for ftype in ("email", "phone", "username", "member_id"):
                    val = (norm.get(ftype) or {}).get("normalized_value") or ""
                    if val and q_lower in val.lower() and val.lower() not in seen:
                        seen.add(val.lower())
                        suggestions.append({"type": ftype, "value": val})
                        if len(suggestions) >= limit:
                            break
                if len(suggestions) >= limit:
                    break
            payload = {"suggestions": suggestions[:limit]}
            cache_set(cache_key, payload, ttl_seconds=120)
            return payload
        except Exception:
            pass

    # Search in email index
    emails = db.collection("indexes").document("email_index").get()
    if emails.exists:
        for email in emails.to_dict().get("values", {}):
            if q_lower in email.lower():
                suggestions.append({"type": "email", "value": email})
                if len(suggestions) >= limit:
                    break

    # Search in phone index
    if len(suggestions) < limit:
        phones = db.collection("indexes").document("phone_index").get()
        if phones.exists:
            for phone in phones.to_dict().get("values", {}):
                if q_lower in phone.lower():
                    suggestions.append({"type": "phone", "value": phone})
                    if len(suggestions) >= limit:
                        break

    # Search in username index
    if len(suggestions) < limit:
        usernames = db.collection("indexes").document("username_index").get()
        if usernames.exists:
            for username in usernames.to_dict().get("values", {}):
                if q_lower in username.lower():
                    suggestions.append({"type": "username", "value": username})
                    if len(suggestions) >= limit:
                        break

    # Search in member_id index
    if len(suggestions) < limit:
        member_ids = db.collection("indexes").document("member_id_index").get()
        if member_ids.exists:
            for mid in member_ids.to_dict().get("values", {}):
                if q_lower in mid.lower():
                    suggestions.append({"type": "member_id", "value": mid})
                    if len(suggestions) >= limit:
                        break

    # Fuzzy fallback (§26): similar indexed values when prefix match is thin
    if len(suggestions) < limit and emails.exists:
        for candidate, score in fuzzy_candidates(q, list(emails.to_dict().get("values", {}).keys())):
            suggestions.append({"type": "email", "value": candidate, "fuzzy_score": score})
            if len(suggestions) >= limit:
                break

    payload = {"suggestions": suggestions[:limit]}
    cache_set(cache_key, payload, ttl_seconds=120)
    return payload
