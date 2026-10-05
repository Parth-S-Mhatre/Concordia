from fastapi import APIRouter, HTTPException
from typing import List

from backend.config import db
from backend.models.schemas import SearchRequest, SearchResponse, EnrichmentStep
from backend.services.cache import cache_get, cache_set
from backend.services.enrichment import progressive_enrichment
from backend.services.fuzzy import fuzzy_candidates
from backend.services.matching import find_matching_records


router = APIRouter()


@router.post("", response_model=SearchResponse)
async def search_entity(request: SearchRequest):
    """Search for an entity using progressive enrichment (cached, §21)."""
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    query = request.query.strip()
    cache_key = f"search:{query.lower()}:{request.limit}"
    cached = cache_get(cache_key)
    if cached:
        return SearchResponse(**cached)

    # Perform progressive enrichment
    result = await progressive_enrichment(query, fuzzy=True)

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
async def get_search_suggestions(q: str = "", limit: int = 10):
    """Get search suggestions based on indexed identifiers (cached)."""
    if not q or len(q) < 2:
        return {"suggestions": []}

    cache_key = f"suggest:{q.lower()}:{limit}"
    cached = cache_get(cache_key)
    if cached:
        return cached

    suggestions = []
    q_lower = q.lower()

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
