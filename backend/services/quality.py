"""Data quality profiling + duplicate-dataset detection (§26 bonus)."""

import hashlib
import json
from collections import Counter
from typing import Dict, List


def fingerprint_dataset(headers: List[str], sample_rows: List[Dict]) -> str:
    payload = json.dumps(
        {"headers": sorted(h.lower() for h in headers), "sample": sample_rows[:5]},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


def profile_records(headers: List[str], rows: List[Dict], max_rows: int = 2000) -> Dict:
    sample = rows[:max_rows]
    total = len(rows)
    columns = []
    seen_hashes: Counter = Counter()
    duplicates = 0
    for header in headers:
        values = [(r.get(header) or "") for r in sample]
        non_blank = sum(1 for v in values if str(v).strip())
        distinct = len(set(str(v).strip().lower() for v in values if str(v).strip()))
        malformed = 0
        lower = header.lower()
        if "email" in lower or "mail" in lower:
            malformed = sum(
                1 for v in values if v and ("@" not in str(v) or "." not in str(v).split("@")[-1])
            )
        if "phone" in lower or "mobile" in lower or "contact" in lower:
            malformed = sum(
                1
                for v in values
                if v and sum(c.isdigit() for c in str(v)) < 7
            )
        columns.append(
            {
                "column": header,
                "non_blank_rate": round(non_blank / max(len(sample), 1), 3),
                "distinct_values": distinct,
                "malformed_values": malformed,
            }
        )
    for row in sample:
        digest = hashlib.md5(
            json.dumps(row, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        seen_hashes[digest] += 1
        if seen_hashes[digest] == 2:
            duplicates += 1
    return {
        "total_rows": total,
        "profiled_rows": len(sample),
        "columns": columns,
        "duplicate_rows_in_sample": duplicates,
    }
