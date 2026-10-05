"""SQL dump ingestion (§4) with multi-table understanding (§15/§16).

Supports MySQL-style dumps:
  CREATE TABLE `members` (...) with optional REFERENCES / FOREIGN KEY lines
  INSERT INTO `members` (...) VALUES (...), (...);

Returns per-table columns, row dicts, explicit FK relationships, and inferred
relationships (shared column names across tables, e.g. member_id).
"""

import re
from typing import Dict, List, Tuple

_CREATE_HEAD_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)[`\"']?\s*\(",
    re.IGNORECASE,
)
_INSERT_RE = re.compile(
    r"INSERT\s+INTO\s+[`\"']?(\w+)[`\"']?\s*(\(([^)]+)\))?\s*VALUES\s*(.*?);",
    re.IGNORECASE | re.DOTALL,
)
_FK_RE = re.compile(
    r"FOREIGN\s+KEY\s*\([`\"']?(\w+)[`\"']?\)\s*REFERENCES\s+[`\"']?(\w+)[`\"']?\s*\([`\"']?(\w+)[`\"']?\)",
    re.IGNORECASE,
)
_REF_RE = re.compile(r"[`\"']?(\w+)[`\"']?\s+.*?REFERENCES\s+[`\"']?(\w+)[`\"']?\s*\([`\"']?(\w+)[`\"']?\)", re.IGNORECASE)


def _split_sql_values(body: str) -> List[str]:
    groups, depth, current, in_str, quote = [], 0, "", False, ""
    i = 0
    while i < len(body):
        ch = body[i]
        if in_str:
            current += ch
            if ch == quote and body[i - 1] != "\\":
                in_str = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_str, quote, current = True, ch, current + ch
        elif ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
            if depth == 0:
                groups.append(current.strip().strip(","))
                current = ""
        else:
            current += ch
        i += 1
    return [g for g in groups if g.strip(" ,")]


def _parse_value(token: str):
    token = token.strip()
    if token.upper() in ("NULL", ""):
        return ""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ("'", '"'):
        return token[1:-1].replace("\\'", "'").replace('\\"', '"')
    return token


def _split_row(group: str) -> List[str]:
    inner = group.strip().lstrip(",").strip()[1:-1]  # strip outer parens
    parts, current, in_str, quote = [], "", False, ""
    for idx, ch in enumerate(inner):
        if in_str:
            current += ch
            if ch == quote and inner[idx - 1] != "\\":
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str, quote = True, ch
            current += ch
        elif ch == ",":
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return parts


def _split_top_level(body: str) -> List[str]:
    """Split a CREATE TABLE body on top-level commas (paren + quote aware)."""
    parts, depth, current, in_str, quote = [], 0, "", False, ""
    for idx, ch in enumerate(body):
        if in_str:
            current += ch
            if ch == quote and body[idx - 1] != "\\":
                in_str = False
            continue
        if ch in ("'", '"', "`"):
            in_str, quote = True, ch
            current += ch
        elif ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth -= 1
            current += ch
        elif ch == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current)
    return parts


def _iter_create_tables(text: str):
    """Yield (table_name, body) with paren-balanced bodies (VARCHAR(20)-safe)."""
    for match in _CREATE_HEAD_RE.finditer(text):
        name, depth, i, in_str, quote = match.group(1), 1, match.end(), False, ""
        body_chars = []
        while i < len(text) and depth > 0:
            ch = text[i]
            if in_str:
                body_chars.append(ch)
                if ch == quote and text[i - 1] != "\\":
                    in_str = False
            elif ch in ("'", '"'):
                in_str, quote = True, ch
                body_chars.append(ch)
            elif ch == "(":
                depth += 1
                body_chars.append(ch)
            elif ch == ")":
                depth -= 1
                if depth > 0:
                    body_chars.append(ch)
            else:
                body_chars.append(ch)
            i += 1
        yield name, "".join(body_chars)


def parse_sql_dump(text: str) -> Tuple[Dict[str, Dict], List[Dict]]:
    """Parse dump text -> ({table: {columns, rows}}, relationships)."""
    tables: Dict[str, Dict] = {}
    create_bodies: Dict[str, str] = {}
    for name, body in _iter_create_tables(text):
        create_bodies[name] = body
        cols = []
        for definition in _split_top_level(body):
            line = definition.strip().rstrip(",")
            if not line or line.upper().startswith(
                ("PRIMARY", "FOREIGN", "KEY", "CONSTRAINT", "UNIQUE", "INDEX", "CHECK")
            ):
                continue
            col = re.split(r"\s+", line.strip("`\"'"))[0].strip("`\"'")
            if col and col not in cols:
                cols.append(col)
        tables[name] = {"columns": cols, "rows": []}

    for match in _INSERT_RE.finditer(text):
        table, col_group, col_list, values_body = (
            match.group(1),
            match.group(2),
            match.group(3),
            match.group(4),
        )
        columns = (
            [c.strip().strip("`\"'") for c in col_list.split(",")]
            if col_list
            else tables.get(table, {}).get("columns", [])
        )
        if table not in tables:
            tables[table] = {"columns": columns, "rows": []}
        for group in _split_sql_values(values_body):
            tokens = _split_row(group)
            row = {
                col: _parse_value(tok)
                for col, tok in zip(columns, tokens)
                if col is not None
            }
            tables[table]["rows"].append(row)
        if columns and not tables[table]["columns"]:
            tables[table]["columns"] = columns

    relationships: List[Dict] = []
    for from_table, body in create_bodies.items():
        for fk in _FK_RE.finditer(body):
            relationships.append(
                {
                    "from_table": from_table,
                    "from_column": fk.group(1),
                    "to_table": fk.group(2),
                    "to_column": fk.group(3),
                    "kind": "foreign_key",
                }
            )
        for ref in _REF_RE.finditer(body):
            rel = {
                "from_table": from_table,
                "from_column": ref.group(1),
                "to_table": ref.group(2),
                "to_column": ref.group(3),
                "kind": "foreign_key",
            }
            if rel not in relationships:
                relationships.append(rel)

    def _linked(a: str, b: str) -> bool:
        pairs = {(r["from_table"], r["to_table"]) for r in relationships} | {
            (r["to_table"], r["from_table"]) for r in relationships
        }
        return (a, b) in pairs

    # Inferred: same column name (ending in _id/id) shared across tables.
    col_to_tables: Dict[str, List[str]] = {}
    for table, info in tables.items():
        for col in info["columns"]:
            col_to_tables.setdefault(col.lower(), []).append(table)
    for col, owners in col_to_tables.items():
        if len(owners) > 1 and (col.endswith("id") or col in ("email", "phone", "username")):
            for i in range(len(owners)):
                for j in range(i + 1, len(owners)):
                    if _linked(owners[i], owners[j]):
                        continue
                    candidate = {
                        "from_table": owners[i],
                        "from_column": col,
                        "to_table": owners[j],
                        "to_column": col,
                        "kind": "inferred_shared_column",
                    }
                    if candidate not in relationships:
                        relationships.append(candidate)

    return tables, relationships


def flatten_tables_for_ingest(
    tables: Dict[str, Dict], join_keys: List[str] | None = None
) -> Tuple[List[str], List[Dict]]:
    """Flatten related tables into one record stream for entity resolution.

    Rows from different tables sharing a join key value are merged so that
    e.g. members + member_details + member_contacts on member_id become one
    logical record (§15 example) while keeping per-table provenance in
    `_source_table`.
    """
    if len(tables) <= 1:
        name = next(iter(tables), "table")
        rows = [dict(r, _source_table=name) for r in tables.get(name, {}).get("rows", [])]
        cols = tables.get(name, {}).get("columns", []) if tables else []
        return cols, rows

    keys = join_keys or ["member_id", "memberid", "id", "email"]
    join_key = next(
        (k for k in keys if sum(k in [c.lower() for c in info["columns"]] for info in tables.values()) >= 2),
        None,
    )
    all_columns: List[str] = []
    for info in tables.values():
        for col in info["columns"]:
            if col not in all_columns:
                all_columns.append(col)

    if not join_key:
        flat = []
        for name, info in tables.items():
            flat.extend(dict(r, _source_table=name) for r in info["rows"])
        return all_columns, flat

    merged: Dict[str, Dict] = {}
    for name, info in tables.items():
        for row in info["rows"]:
            key_val = next(
                (str(row.get(c, "")) for c in info["columns"] if c.lower() == join_key and row.get(c)),
                None,
            )
            bucket = key_val or f"__row:{name}:{len(merged)}"
            target = merged.setdefault(bucket, {"_source_table": name})
            for col, val in row.items():
                if val not in (None, "") or col not in target:
                    target[col] = val
            target["_source_table"] = f"{target['_source_table']}+{name}" if bucket in merged and "+" not in target["_source_table"] and target["_source_table"] != name else target.get("_source_table", name)
    return all_columns, list(merged.values())
