from typing import List, Dict, Set, Optional, Tuple
from backend.config import db, COLLECTION_ENTITIES, COLLECTION_RECORDS, COLLECTION_SOURCES
from backend.models.schemas import Entity, EntityField, EnrichmentStep
from backend.services.fuzzy import CONFIDENCE, fuzzy_candidates, resolve_conflict
from backend.services.matching import find_matching_records, extract_identifiers, get_index
from backend.services.normalization import normalize_value
import re


async def progressive_enrichment(initial_query: str, fuzzy: bool = False, user: dict | None = None) -> Optional[Tuple[Entity, List[EnrichmentStep], List[str]]]:
    from backend.services.auth import get_owner_uid, is_visible
    owner_uid = get_owner_uid(user)
    query = initial_query.strip()
    if not query:
        return None
    
    identifier_type = detect_identifier_type(query)
    normalized_query = normalize_identifier(query, identifier_type)
    
    if not normalized_query:
        return None
    
    queue = [(normalized_query, identifier_type, 0)]
    visited: Set[Tuple[str, str]] = set()
    matched_records: List[Dict] = []
    enrichment_steps: List[EnrichmentStep] = []
    step_counter = 0
    
    while queue:
        identifier_value, identifier_type, step = queue.pop(0)
        visit_key = (identifier_value, identifier_type)
        if visit_key in visited:
            continue
        visited.add(visit_key)
        
        records = await find_matching_records(identifier_value, identifier_type, user=user, owner_uid=owner_uid)
        if not records and fuzzy and identifier_type in ("email", "username"):
            for candidate, _ in fuzzy_candidates(identifier_value, list(get_index(identifier_type).keys()))[:3]:
                records.extend(await find_matching_records(candidate, identifier_type, user=user, owner_uid=owner_uid))
        
        if records:
            # Drop records whose source belongs to another owner (extra guard).
            filtered = []
            for r in records:
                try:
                    sdoc = db.collection(COLLECTION_SOURCES).document(r.source_id).get()
                    if sdoc.exists and not is_visible(sdoc.to_dict(), user):
                        continue
                except Exception:
                    pass
                filtered.append(r)
            records = filtered
        if records:
            step_counter += 1
            source_ids = set(r.source_id for r in records)
            source_names = []
            for sid in source_ids:
                sdoc = db.collection(COLLECTION_SOURCES).document(sid).get()
                if sdoc.exists:
                    source_names.append(sdoc.to_dict().get("name", sid))
            
            discovered_fields = {}
            for record in records:
                for field_type, norm_val in record.normalized_data.items():
                    if norm_val.normalized_value:
                        discovered_fields[field_type] = norm_val.normalized_value
            
            enrichment_steps.append(EnrichmentStep(
                step=step_counter,
                identifier_type=identifier_type,
                identifier_value=identifier_value,
                source_id=", ".join(source_ids),
                source_name=", ".join(source_names),
                discovered_fields=discovered_fields,
            ))
            
            for record in records:
                if not any(r.get("record_id") == record.record_id for r in matched_records):
                    matched_records.append({
                        "record_id": record.record_id,
                        "source_id": record.source_id,
                        "source_row_id": record.source_row_id,
                        "normalized_data": record.normalized_data,
                        "raw_data": record.raw_data,
                    })
            
            for record in records:
                identifiers = extract_identifiers(record)
                for id_type, id_value in identifiers.items():
                    if id_value and (id_value, id_type) not in visited:
                        queue.append((id_value, id_type, step + 1))
    
    if not matched_records:
        return None
    
    entity = await build_master_entity(matched_records, user=user)

    # Persist enrichment trail + timeline on the entity for traceability UI.
    trail = [step.model_dump() for step in enrichment_steps]
    history = [
        {"event": "created", "detail": f"Assembled from {len(matched_records)} record(s)."},
        *[
            {
                "event": "enriched",
                "detail": f"{s.identifier_type}:{s.identifier_value} via {s.source_name}",
            }
            for s in enrichment_steps
        ],
    ]
    try:
        db.collection(COLLECTION_ENTITIES).document(entity.entity_id).update(
            {"enrichment_path": trail, "history": history}
        )
    except Exception:
        pass

    source_ids = list(set(r["source_id"] for r in matched_records))
    source_names = []
    for sid in source_ids:
        sdoc = db.collection(COLLECTION_SOURCES).document(sid).get()
        if sdoc.exists:
            source_names.append(sdoc.to_dict().get("name", sid))
    
    return entity, enrichment_steps, source_names


def detect_identifier_type(query: str) -> str:
    query = query.strip()
    if "@" in query and "." in query.split("@")[-1]:
        return "email"
    cleaned = query.replace("+", "").replace("-", "").replace(" ", "")
    if cleaned.isdigit() and len(cleaned) >= 10:
        return "phone"
    if re.match(r'^[A-Z]{2,}\d+$', query, re.IGNORECASE):
        return "member_id"
    if re.match(r'^[\w.-]+$', query) and " " not in query:
        return "username"
    return "email" if "@" in query else "username"


def normalize_identifier(query: str, identifier_type: str) -> str:
    norm = normalize_value(query, identifier_type)
    return norm.normalized_value


async def build_master_entity(matched_records: List[Dict], user: dict | None = None) -> Entity:
    import uuid
    from datetime import datetime
    from backend.services.auth import get_owner_uid

    owner_uid = get_owner_uid(user)
    
    field_values: Dict[str, List[Dict]] = {
        "email": [], "phone": [], "username": [], "member_id": [],
        "name": [], "address": [], "company": [],
    }
    
    source_ids = set()
    record_ids = []
    
    for record in matched_records:
        source_ids.add(record["source_id"])
        record_ids.append(record["record_id"])
        
        for field_type, norm_value in record["normalized_data"].items():
            if norm_value.normalized_value:
                field_values[field_type].append({
                    "value": norm_value.normalized_value,
                    "source_id": record["source_id"],
                    "source_record_id": record["record_id"],
                    "source_field": field_type,
                    "original_value": norm_value.original_value,
                    "confidence": CONFIDENCE.get(field_type, 0.6),
                })

    entity_fields = {}
    for field_type, values in field_values.items():
        if values:
            grouped: Dict[str, List[Dict]] = {}
            for candidate in values:
                grouped.setdefault(candidate["value"], []).append(candidate)
            ranked = [
                {**items[0], "source_count": len(items)}
                for items in grouped.values()
            ]
            entity_fields[field_type] = EntityField(**resolve_conflict(ranked))
    
    entity_id = generate_entity_id(entity_fields, owner_uid=owner_uid)
    
    existing = db.collection(COLLECTION_ENTITIES).document(entity_id).get()
    if existing.exists:
        entity = merge_entities(Entity(**existing.to_dict()), entity_fields, source_ids, record_ids)
    else:
        entity = Entity(
            entity_id=entity_id,
            source_ids=list(source_ids),
            record_ids=record_ids,
            **entity_fields,
        )
    
    payload = entity.model_dump()
    if owner_uid:
        payload["owner_uid"] = owner_uid
    if user and user.get("email"):
        payload["owner_email"] = user.get("email")
    db.collection(COLLECTION_ENTITIES).document(entity_id).set(payload)
    # Keep the in-memory object in sync for the API response.
    entity = Entity(**payload)
    return entity


def generate_entity_id(fields: Dict[str, EntityField], owner_uid: str | None = None) -> str:
    base = None
    for field_type in ["email", "phone", "username", "member_id"]:
        if field_type in fields:
            value = fields[field_type].value
            import hashlib
            hash_input = f"{field_type}:{value}".encode()
            hash_val = hashlib.md5(hash_input).hexdigest()[:8]
            base = f"ENT-{hash_val.upper()}"
            break
    if base is None:
        import uuid
        base = f"ENT-{str(uuid.uuid4())[:8].upper()}"
    # Namespace per owner so two users with the same email never collide.
    if owner_uid:
        import hashlib
        suffix = hashlib.md5(owner_uid.encode()).hexdigest()[:4].upper()
        return f"{base}-{suffix}"
    return base


def merge_entities(existing: Entity, new_fields: Dict[str, EntityField], new_source_ids: Set[str], new_record_ids: List[str]) -> Entity:
    for field_type, new_field in new_fields.items():
        existing_field = getattr(existing, field_type, None)
        if not existing_field or new_field.confidence >= existing_field.confidence:
            setattr(existing, field_type, new_field)
    
    existing.source_ids = list(set(existing.source_ids) | new_source_ids)
    existing.record_ids = list(set(existing.record_ids) | set(new_record_ids))
    existing.updated_at = __import__('datetime').datetime.utcnow()
    
    db.collection(COLLECTION_ENTITIES).document(existing.entity_id).set(existing.model_dump())
    return existing