"""
NVIDIA NIM Service
This is the ONLY service that communicates with NVIDIA NIM API.
The API key is kept server-side only and never exposed to frontend.
"""
import json
import httpx
from typing import List
from backend.config import settings
from backend.models.schemas import FieldMapping, CANONICAL_FIELDS


class NIMService:
    """Service for communicating with NVIDIA NIM API."""
    
    def __init__(self):
        self.api_key = settings.nvidia_nim_api_key
        self.base_url = "https://integrate.api.nvidia.com/v1"
        self.model = "nvidia/nemotron-3-ultra-550b-a55b"
    
    def is_available(self) -> bool:
        """Check if NIM service is configured."""
        return bool(self.api_key)
    
    async def map_fields(self, columns: List[str]) -> List[FieldMapping]:
        """
        Map source columns to canonical fields using NIM.
        Returns empty list if NIM is unavailable or fails.
        """
        if not self.is_available():
            return []
        
        try:
            return await self._call_nim_mapping(columns)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return []
    
    async def _call_nim_mapping(self, columns: List[str]) -> List[FieldMapping]:
        """Call NIM API for field mapping."""
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        prompt = self._build_mapping_prompt(columns)
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "top_p": 0.95,
            "max_tokens": 2048,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": True},
        }

        content_parts = []
        timeout = httpx.Timeout(120.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_line = line[5:].strip()
                    if not data_line or data_line == "[DONE]":
                        continue
                    chunk = json.loads(data_line)
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        content_parts.append(content)

        return self._parse_mapping_response("".join(content_parts), columns)
    
    def _build_mapping_prompt(self, columns: List[str]) -> str:
        """Build the prompt for field mapping."""
        return f"""Map these source columns to canonical fields. Return ONLY valid JSON array.

Source columns: {json.dumps(columns)}

Canonical fields: {json.dumps(CANONICAL_FIELDS)}

Return format (JSON array only):
[
  {{"source_column": "col_name", "canonical_field": "canonical_name", "confidence": 0.95}},
  ...
]

Rules:
- Each source column maps to at most one canonical field
- Each canonical field used at most once
- If no good match, use empty string for canonical_field
- Confidence 0.0 to 1.0
- Output ONLY the JSON array, no extra text"""
    
    def _parse_mapping_response(self, content: str, columns: List[str]) -> List[FieldMapping]:
        """Parse NIM response into FieldMapping objects."""
        try:
            # Extract JSON array from response
            start = content.find("[")
            end = content.rfind("]") + 1
            if start >= 0 and end > start:
                json_str = content[start:end]
                mappings_data = json.loads(json_str)
                if not isinstance(mappings_data, list):
                    return []

                suggestions = []
                seen_columns = set()
                used_fields = set()
                for m in mappings_data:
                    if not isinstance(m, dict):
                        continue
                    source_column = m.get("source_column")
                    canonical_field = m.get("canonical_field")
                    if source_column not in columns or source_column in seen_columns:
                        continue
                    if canonical_field not in CANONICAL_FIELDS or canonical_field in used_fields:
                        continue
                    confidence = float(m.get("confidence", 0.0))
                    if not 0.0 <= confidence <= 1.0:
                        continue
                    suggestions.append(FieldMapping(
                        source_column=source_column,
                        canonical_field=canonical_field,
                        confidence=confidence,
                        is_reviewed=False,
                    ))
                    seen_columns.add(source_column)
                    used_fields.add(canonical_field)
                return suggestions
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        
        return []


# Singleton instance
nim_service = NIMService()


async def suggest_field_mappings_nim(columns: List[str]) -> List[FieldMapping]:
    """Public function to get NIM field mappings."""
    return await nim_service.map_fields(columns)