from fastapi import APIRouter, HTTPException
from typing import List, Optional

from backend.config import db, COLLECTION_ENTITIES, COLLECTION_RECORDS
from backend.models.schemas import Entity, EntityField


router = APIRouter()


@router.get("/stats/summary")
async def get_entity_stats():
    """Get entity statistics for dashboard."""
    entities = db.collection(COLLECTION_ENTITIES).stream()
    total = 0
    with_email = 0
    with_phone = 0
    with_username = 0
    with_member_id = 0
    multi_source = 0

    for e in entities:
        total += 1
        data = e.to_dict()
        if data.get("email"):
            with_email += 1
        if data.get("phone"):
            with_phone += 1
        if data.get("username"):
            with_username += 1
        if data.get("member_id"):
            with_member_id += 1
        if len(data.get("source_ids", [])) > 1:
            multi_source += 1

    return {
        "total_entities": total,
        "with_email": with_email,
        "with_phone": with_phone,
        "with_username": with_username,
        "with_member_id": with_member_id,
        "multi_source_entities": multi_source,
        "single_source_entities": total - multi_source,
    }


@router.get("", response_model=List[Entity])
async def list_entities(
    limit: int = 50,
    offset: int = 0,
    q: Optional[str] = None,
    multi_source_only: bool = False,
):
    """List master entities with optional search + multi-source filter (§26 advanced search)."""
    docs = db.collection(COLLECTION_ENTITIES).order_by("updated_at", direction="DESCENDING").limit(500).stream()
    entities = [Entity(**doc.to_dict()) for doc in docs]
    if multi_source_only:
        entities = [e for e in entities if len(e.source_ids or []) > 1]
    if q:
        needle = q.strip().lower()
        scored = []
        for entity in entities:
            blob = " ".join(
                str((getattr(entity, field) or {}).get("value", "") if isinstance(getattr(entity, field), dict) else getattr(getattr(entity, field, None), "value", ""))
                for field in ("name", "email", "phone", "username", "member_id", "address", "company")
            ).lower()
            if needle in blob or needle in entity.entity_id.lower():
                scored.append(entity)
        entities = scored
    return entities[offset : offset + limit]


@router.get("/{entity_id}", response_model=Entity)
async def get_entity(entity_id: str):
    """Get a specific master entity with full traceability."""
    doc = db.collection(COLLECTION_ENTITIES).document(entity_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Entity not found")
    return Entity(**doc.to_dict())


@router.get("/{entity_id}/traceability")
async def get_entity_traceability(entity_id: str):
    """Get detailed source traceability for an entity."""
    doc = db.collection(COLLECTION_ENTITIES).document(entity_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity = doc.to_dict()

    # Build traceability report
    traceability = {}
    for field_name in ["email", "phone", "username", "member_id", "name", "address", "company"]:
        field_data = entity.get(field_name)
        if field_data:
            traceability[field_name] = {
                "value": field_data.get("value"),
                "source_id": field_data.get("source_id"),
                "source_record_id": field_data.get("source_record_id"),
                "source_field": field_data.get("source_field"),
                "original_value": field_data.get("original_value"),
                "confidence": field_data.get("confidence", 1.0),
            }

    # Get source names
    source_ids = entity.get("source_ids", [])
    sources = {}
    for sid in source_ids:
        sdoc = db.collection("sources").document(sid).get()
        if sdoc.exists:
            sources[sid] = sdoc.to_dict().get("name", sid)

    return {
        "entity_id": entity_id,
        "traceability": traceability,
        "sources": sources,
        "record_ids": entity.get("record_ids", []),
    }


@router.get("/{entity_id}/enrichment-path")
async def get_enrichment_path(entity_id: str):
    """Get the enrichment path showing how the entity was built."""
    doc = db.collection(COLLECTION_ENTITIES).document(entity_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity = doc.to_dict()
    enrichment_path = entity.get("enrichment_path", [])

    return {
        "entity_id": entity_id,
        "enrichment_path": enrichment_path,
    }


@router.get("/{entity_id}/history")
async def get_entity_history(entity_id: str):
    """Entity timeline: creation + enrichment events (§26 bonus)."""
    doc = db.collection(COLLECTION_ENTITIES).document(entity_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity = doc.to_dict()
    history = entity.get("history", [])
    if not history:
        history = [
            {
                "event": "created",
                "at": str(entity.get("created_at")),
                "detail": f"Entity assembled from {len(entity.get('record_ids', []))} record(s).",
            }
        ]
        for step in entity.get("enrichment_path", []):
            history.append(
                {
                    "event": "enriched",
                    "at": str(entity.get("updated_at")),
                    "detail": f"{step.get('identifier_type')}:{step.get('identifier_value')} via {step.get('source_name')}",
                }
            )
    return {"entity_id": entity_id, "history": history}


@router.get("/{entity_id}/graph")
async def get_entity_graph(entity_id: str):
    """Graph data for relationship visualization (§26 bonus)."""
    doc = db.collection(COLLECTION_ENTITIES).document(entity_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Entity not found")
    entity = doc.to_dict()
    nodes = [{"id": entity_id, "label": entity_id, "kind": "entity"}]
    edges = []
    for sid in entity.get("source_ids", []):
        sdoc = db.collection("sources").document(sid).get()
        label = sdoc.to_dict().get("name", sid) if sdoc.exists else sid
        nodes.append({"id": f"src:{sid}", "label": label, "kind": "source"})
        edges.append({"from": entity_id, "to": f"src:{sid}"})
    for field in ("email", "phone", "username", "member_id"):
        value = (entity.get(field) or {}).get("value")
        if value:
            nid = f"{field}:{value}"
            nodes.append({"id": nid, "label": f"{field}: {value}", "kind": "identifier"})
            edges.append({"from": entity_id, "to": nid})
    return {"entity_id": entity_id, "nodes": nodes, "edges": edges}
