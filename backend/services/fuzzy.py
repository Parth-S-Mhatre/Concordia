"""Fuzzy matching + confidence scoring + conflict resolution (§26 bonus).

Exact rules keep priority (email 1.0 > phone 0.95 > member_id 0.95 >
username 0.9). Fuzzy rules extend the hierarchy without replacing it:
name similarity, email local-part similarity, phone digit containment.
"""

import difflib
import re
from typing import Dict, List, Tuple

CONFIDENCE = {
    "email": 1.0,
    "phone": 0.95,
    "member_id": 0.95,
    "username": 0.9,
    "email_local_fuzzy": 0.75,
    "name_fuzzy": 0.65,
    "phone_containment": 0.8,
}


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def fuzzy_candidates(query: str, indexed_values: List[str], threshold: float = 0.85) -> List[Tuple[str, float]]:
    results = []
    q = (query or "").strip().lower()
    if not q:
        return results
    for value in indexed_values:
        score = similarity(q, str(value))
        if score >= threshold:
            results.append((value, round(score * CONFIDENCE["name_fuzzy"] / 0.65, 3)))
    return sorted(results, key=lambda item: item[1], reverse=True)[:10]


def phone_contains(query: str, indexed: str) -> bool:
    qd, idg = _digits(query), _digits(indexed)
    return bool(qd and idg) and (qd in idg or idg in qd) and abs(len(qd) - len(idg)) <= 3


def email_local_match(a: str, b: str) -> bool:
    la, lb = (a or "").split("@")[0].lower(), (b or "").split("@")[0].lower()
    return bool(la and lb) and (la == lb or similarity(la, lb) >= 0.9)


def resolve_conflict(candidates: List[Dict]) -> Dict | None:
    """Pick winning field value: highest confidence, then most sources, then longest value."""
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda c: (c.get("confidence", 0), c.get("source_count", 1), len(str(c.get("value", "")))),
        reverse=True,
    )[0]
