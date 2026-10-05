from typing import List, Dict, Any
from backend.config import settings
from backend.models.schemas import FieldMapping, CANONICAL_FIELDS
from backend.services.nim import suggest_field_mappings_nim


# Deterministic rule-based mapping (fallback when NIM is unavailable)
RULE_BASED_MAPPINGS = {
    "email": ["email", "email_id", "email_address", "contact_email", "e_mail", "mail"],
    "phone": ["phone", "mobile", "mobile_number", "contact_no", "phone_number", "telephone", "cell", "contact"],
    "username": ["username", "user_name", "user", "login", "handle", "alias"],
    "member_id": ["member_id", "member_no", "customer_id", "user_id", "memberid", "customerid", "userid"],
    "name": ["name", "full_name", "person_name", "first_name", "last_name", "fname", "lname"],
    "address": ["address", "addr", "street", "city", "state", "zip", "postal_code", "location"],
    "company": ["company", "company_name", "organization", "org", "employer", "firm"],
}


def normalize_column_name(col: str) -> str:
    """Normalize column name for comparison."""
    return col.lower().replace("_", "").replace("-", "").replace(" ", "")


def rule_based_mapping(columns: List[str]) -> List[FieldMapping]:
    """Apply deterministic rule-based field mapping."""
    suggestions = []
    used_canonical = set()
    
    for col in columns:
        col_norm = normalize_column_name(col)
        best_match = None
        best_score = 0
        
        for canonical, variants in RULE_BASED_MAPPINGS.items():
            if canonical in used_canonical:
                continue
            for variant in variants:
                var_norm = normalize_column_name(variant)
                if col_norm == var_norm:
                    best_match = canonical
                    best_score = 1.0
                    break
                elif var_norm in col_norm or col_norm in var_norm:
                    if best_score < 0.8:
                        best_match = canonical
                        best_score = 0.8
        
        if best_match:
            suggestions.append(FieldMapping(
                source_column=col,
                canonical_field=best_match,
                confidence=best_score,
                is_reviewed=False,
            ))
            used_canonical.add(best_match)
        else:
            suggestions.append(FieldMapping(
                source_column=col,
                canonical_field="",
                confidence=0.0,
                is_reviewed=False,
            ))
    
    return suggestions


async def suggest_field_mappings(columns: List[str]) -> List[FieldMapping]:
    """
    Get field mapping suggestions from NVIDIA NIM.
    Falls back to rule-based mapping if NIM is unavailable.
    """
    # Try NIM first
    if settings.nvidia_nim_api_key:
        try:
            nim_suggestions = await suggest_field_mappings_nim(columns)
            if nim_suggestions:
                return nim_suggestions
        except Exception:
            pass
    
    # Fallback to rule-based
    return rule_based_mapping(columns)


def apply_field_mappings(raw_row: Dict[str, Any], mappings: List[FieldMapping]) -> Dict[str, Any]:
    """Apply confirmed mappings to a raw row."""
    result = {}
    for mapping in mappings:
        if mapping.canonical_field and mapping.source_column in raw_row:
            result[mapping.canonical_field] = raw_row[mapping.source_column]
    return result