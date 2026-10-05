import re
from typing import Dict, Any
from backend.models.schemas import NormalizedValue


def normalize_email(value: str) -> NormalizedValue:
    """Normalize email address."""
    original = value
    if not value:
        return NormalizedValue(original_value=original, normalized_value="", field_type="email")
    
    # Strip whitespace and lowercase
    normalized = value.strip().lower()
    
    # Basic validation - must have @ and domain
    if "@" not in normalized:
        return NormalizedValue(original_value=original, normalized_value="", field_type="email")
    
    return NormalizedValue(original_value=original, normalized_value=normalized, field_type="email")


def normalize_phone(value: str) -> NormalizedValue:
    """Normalize phone number."""
    original = value
    if not value:
        return NormalizedValue(original_value=original, normalized_value="", field_type="phone")
    
    # Remove all non-digit characters except +
    normalized = re.sub(r"[^\d+]", "", value.strip())
    
    # Handle Indian numbers (+91)
    if normalized.startswith("+91"):
        normalized = "+91" + normalized[3:]
    elif normalized.startswith("91") and len(normalized) == 12:
        normalized = "+" + normalized
    elif len(normalized) == 10:
        normalized = "+91" + normalized
    
    return NormalizedValue(original_value=original, normalized_value=normalized, field_type="phone")


def normalize_name(value: str) -> NormalizedValue:
    """Normalize person name."""
    original = value
    if not value:
        return NormalizedValue(original_value=original, normalized_value="", field_type="name")
    
    # Strip whitespace, title case
    normalized = " ".join(word.capitalize() for word in value.strip().split())
    
    return NormalizedValue(original_value=original, normalized_value=normalized, field_type="name")


def normalize_text(value: str) -> NormalizedValue:
    """Normalize generic text field."""
    original = value
    if not value:
        return NormalizedValue(original_value=original, normalized_value="", field_type="text")
    
    normalized = value.strip()
    return NormalizedValue(original_value=original, normalized_value=normalized, field_type="text")


def normalize_value(value: str, field_type: str) -> NormalizedValue:
    """Dispatch to appropriate normalizer based on field type."""
    normalizers = {
        "email": normalize_email,
        "phone": normalize_phone,
        "name": normalize_name,
        "username": normalize_text,
        "member_id": normalize_text,
        "address": normalize_text,
        "company": normalize_text,
    }
    
    normalizer = normalizers.get(field_type, normalize_text)
    return normalizer(value)


def normalize_record(mapped_data: Dict[str, str]) -> Dict[str, NormalizedValue]:
    """Normalize all fields in a mapped record."""
    normalized = {}
    for field_type, value in mapped_data.items():
        if value:
            normalized[field_type] = normalize_value(value, field_type)
    return normalized