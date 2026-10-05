from typing import Dict, List, Set, Optional
from backend.config import db, COLLECTION_RECORDS, COLLECTION_INDEXES
from backend.models.schemas import Record, NormalizedValue


# In-memory indexes for MVP (can be replaced with persistent storage)
# Structure: {index_name: {normalized_value: set(record_ids)}}
_indexes: Dict[str, Dict[str, Set[str]]] = {
    "email": {},
    "phone": {},
    "username": {},
    "member_id": {},
}


def get_index(index_name: str) -> Dict[str, Set[str]]:
    """Get or create an index."""
    if index_name not in _indexes:
        _indexes[index_name] = {}
    return _indexes[index_name]


def add_to_index(index_name: str, value: str, record_id: str):
    """Add a record ID to an index for a normalized value."""
    if not value:
        return
    index = get_index(index_name)
    if value not in index:
        index[value] = set()
    index[value].add(record_id)


def remove_from_index(index_name: str, value: str, record_id: str):
    """Remove a record ID from an index."""
    if not value:
        return
    index = get_index(index_name)
    if value in index:
        index[value].discard(record_id)
        if not index[value]:
            del index[value]


def find_in_index(index_name: str, value: str) -> Set[str]:
    """Find record IDs matching a normalized value in an index."""
    if not value:
        return set()
    index = get_index(index_name)
    return index.get(value, set())


def clear_indexes():
    """Clear all in-memory indexes (for testing)."""
    global _indexes
    _indexes = {
        "email": {},
        "phone": {},
        "username": {},
        "member_id": {},
    }


async def persist_indexes():
    """Persist indexes to Firestore (for recovery)."""
    for index_name, index_data in _indexes.items():
        # Convert sets to lists for Firestore
        serializable = {k: list(v) for k, v in index_data.items()}
        db.collection(COLLECTION_INDEXES).document(f"{index_name}_index").set({
            "values": serializable,
            "updated_at": "auto",
        })


async def load_indexes():
    """Load indexes from Firestore."""
    global _indexes
    for index_name in ["email", "phone", "username", "member_id"]:
        doc = db.collection(COLLECTION_INDEXES).document(f"{index_name}_index").get()
        if doc.exists:
            data = doc.to_dict()
            _indexes[index_name] = {k: set(v) for k, v in data.get("values", {}).items()}


async def update_indexes(record: Record):
    """Update all indexes for a record."""
    for field_type, norm_value in record.normalized_data.items():
        if field_type in ["email", "phone", "username", "member_id"]:
            add_to_index(field_type, norm_value.normalized_value, record.record_id)


async def find_matching_records(identifier: str, identifier_type: str = None) -> List[Record]:
    """
    Find records matching an identifier.
    If identifier_type is not specified, search all indexes.
    """
    results = []
    seen_record_ids = set()
    
    if identifier_type:
        # Search specific index
        record_ids = find_in_index(identifier_type, identifier)
        for rid in record_ids:
            if rid not in seen_record_ids:
                doc = db.collection(COLLECTION_RECORDS).document(rid).get()
                if doc.exists:
                    results.append(Record(**doc.to_dict()))
                    seen_record_ids.add(rid)
    else:
        # Search all indexes
        for idx_name in ["email", "phone", "username", "member_id"]:
            record_ids = find_in_index(idx_name, identifier)
            for rid in record_ids:
                if rid not in seen_record_ids:
                    doc = db.collection(COLLECTION_RECORDS).document(rid).get()
                    if doc.exists:
                        results.append(Record(**doc.to_dict()))
                        seen_record_ids.add(rid)
    
    return results


def extract_identifiers(record: Record) -> Dict[str, str]:
    """Extract all identifiers from a record for enrichment."""
    identifiers = {}
    for field_type, norm_value in record.normalized_data.items():
        if field_type in ["email", "phone", "username", "member_id"] and norm_value.normalized_value:
            identifiers[field_type] = norm_value.normalized_value
    return identifiers


# Matching rules configuration
MATCH_RULES = [
    ("email", 1),
    ("phone", 2),
    ("username", 3),
    ("member_id", 4),
]


def get_match_priority(field_type: str) -> int:
    """Get priority for a match rule (lower = higher priority)."""
    for ft, priority in MATCH_RULES:
        if ft == field_type:
            return priority
    return 999