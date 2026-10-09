from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks, Request
from typing import List
import hashlib
import uuid
import csv
import io
import json
from datetime import datetime

from backend.config import db, settings, COLLECTION_SOURCES, COLLECTION_RECORDS, COLLECTION_PROCESSING_JOBS
from backend.models.schemas import (
    Source, SourceCreate, SourceUpdate, SourceSchema, SchemaColumn,
    FieldMapping, MappingRequest, MappingResponse, SourceStatus, CANONICAL_FIELDS,
)
from backend.services.mapping import suggest_field_mappings
from backend.services.auth import require_admin, resolve_user, get_owner_uid, is_visible
from backend.services.quality import file_hash, fingerprint_dataset, profile_records
from backend.services.sql_ingest import parse_sql_dump, flatten_tables_for_ingest

router = APIRouter()


def _user(request: Request) -> dict:
    return getattr(request.state, "user", {"uid": None, "email": None, "admin": False, "anonymous": True})


def _check_visible(doc_data: dict | None, user: dict, not_found_msg: str = "Source not found"):
    if not doc_data or not is_visible(doc_data, user):
        raise HTTPException(status_code=404, detail=not_found_msg)
    return doc_data


@router.post("", response_model=Source, status_code=201)
async def create_source(source: SourceCreate, request: Request):
    """Create a new source entry (owner-scoped so new users start clean)."""
    user = _user(request)
    owner_uid = get_owner_uid(user)
    source_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow()
    
    source_data = {
        "source_id": source_id,
        "name": source.name,
        "filename": source.filename,
        "type": source.type,
        "parent_group_id": source.parent_group_id,
        "part_number": source.part_number,
        "status": SourceStatus.UPLOADED,
        "total_records": 0,
        "processed_records": 0,
        "matched_records": 0,
        "new_entities": 0,
        "enriched_entities": 0,
        "file_hash": None,
        "duplicate_of": None,
        "tables": [],
        "created_at": now,
        "updated_at": now,
    }
    if owner_uid:
        source_data["owner_uid"] = owner_uid
        if user.get("email"):
            source_data["owner_email"] = user.get("email")
    
    db.collection(COLLECTION_SOURCES).document(source_id).set(source_data)
    return Source(**source_data)


@router.get("", response_model=List[Source])
async def list_sources(request: Request):
    """List sources visible to the caller (new users see an empty list)."""
    user = _user(request)
    docs = db.collection(COLLECTION_SOURCES).order_by("created_at", direction="DESCENDING").stream()
    out = []
    for doc in docs:
        data = doc.to_dict()
        if is_visible(data, user):
            out.append(Source(**data))
    return out


@router.get("/{source_id}", response_model=Source)
async def get_source(source_id: str, request: Request):
    """Get a specific source."""
    user = _user(request)
    doc = db.collection(COLLECTION_SOURCES).document(source_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    _check_visible(doc.to_dict(), user)
    return Source(**doc.to_dict())


@router.patch("/{source_id}", response_model=Source)
async def update_source(source_id: str, update: SourceUpdate, request: Request):
    """Update source metadata."""
    user = _user(request)
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    _check_visible(doc.to_dict(), user)
    
    update_data = update.model_dump(exclude_unset=True)
    update_data["updated_at"] = datetime.utcnow()
    doc_ref.update(update_data)
    
    updated_doc = doc_ref.get()
    return Source(**updated_doc.to_dict())


@router.delete("/{source_id}")
async def delete_source(source_id: str, request: Request, user: dict = Depends(require_admin)):
    """Delete a source and its records (admin only when auth is enforced)."""
    caller = _user(request)
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    # Owners may delete their own sources; admins may delete visible ones.
    data = doc.to_dict()
    if not (is_visible(data, caller) or (caller.get("uid") and data.get("owner_uid") == caller.get("uid"))):
        raise HTTPException(status_code=404, detail="Source not found")
    
    # Delete associated records
    records = db.collection(COLLECTION_RECORDS).where("source_id", "==", source_id).stream()
    batch = db.batch()
    for record in records:
        batch.delete(record.reference)
    batch.commit()
    
    # Delete source
    doc_ref.delete()
    return {"message": "Source deleted successfully"}


@router.post("/{source_id}/upload")
async def upload_csv(source_id: str, request: Request, file: UploadFile = File(...)):
    """Upload a CSV or SQL dump (§4). SQL tables are flattened on shared keys (§15)."""
    user = _user(request)
    owner_uid = get_owner_uid(user)
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    source_data = doc.to_dict()
    _check_visible(source_data, user)
    safe_filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    lower = safe_filename.lower()
    if not (lower.endswith(".csv") or lower.endswith(".sql")):
        raise HTTPException(status_code=400, detail="Only CSV and SQL dump (.sql) files are allowed")
    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File size exceeds {settings.max_file_size_mb}MB limit")

    digest = file_hash(content)
    duplicate_of = None
    for other in db.collection(COLLECTION_SOURCES).stream():
        data = other.to_dict()
        # Duplicate detection is owner-scoped: a new user's file must not
        # be flagged as a duplicate of the admin demo data.
        if not is_visible(data, user):
            continue
        if other.id != source_id and data.get("file_hash") == digest:
            duplicate_of = data.get("source_id", other.id)
            break

    headers: List[str] = []
    rows: List[dict] = []
    table_names: List[str] = []
    relationships: List[dict] = []
    try:
        if lower.endswith(".sql"):
            text_content = content.decode("utf-8-sig")
            tables, relationships = parse_sql_dump(text_content)
            if not tables or not any(info["rows"] for info in tables.values()):
                raise ValueError("SQL dump contains no INSERT rows")
            table_names = list(tables.keys())
            headers, flat = flatten_tables_for_ingest(tables)
            rows = [{k: v for k, v in r.items() if k != "_source_table"} for r in flat]
        else:
            text_content = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text_content))
            headers = reader.fieldnames or []
            if not headers:
                raise ValueError("CSV has no header row")
            rows = [
                {str(k): v for k, v in row.items() if k is not None and v is not None}
                for row in reader
            ]
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        doc_ref.update({"status": SourceStatus.FAILED, "updated_at": datetime.utcnow()})
        raise HTTPException(status_code=400, detail=f"Invalid file format: {exc}")

    doc_ref.update({"status": SourceStatus.INSPECTING, "updated_at": datetime.utcnow()})
    batch_limit = min(max(settings.batch_size, 1), 450)
    write_batch = db.batch()
    pending = 0
    total_records = 0
    seen_row_hashes = set()  # within-file dedup (also guards multi-part re-uploads)
    skipped_duplicates = 0
    for row in rows:
        raw_data = {str(k): v for k, v in row.items()}
        row_digest = hashlib.md5(json.dumps(raw_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if row_digest in seen_row_hashes:
            skipped_duplicates += 1
            continue
        seen_row_hashes.add(row_digest)
        if len(json.dumps(raw_data, ensure_ascii=False).encode("utf-8")) > 900_000:
            raise HTTPException(status_code=400, detail=f"Row {total_records + 2} exceeds Firestore's document size limit")
        record_id = str(uuid.uuid4())
        record_data = {
            "record_id": record_id,
            "source_id": source_id,
            "source_row_id": total_records + 1,
            "raw_data": raw_data,
            "row_hash": row_digest,
            "normalized_data": {},
            "created_at": datetime.utcnow(),
        }
        if owner_uid:
            record_data["owner_uid"] = owner_uid
            if user.get("email"):
                record_data["owner_email"] = user.get("email")
        write_batch.set(db.collection(COLLECTION_RECORDS).document(record_id), record_data)
        total_records += 1
        pending += 1
        if pending >= batch_limit:
            write_batch.commit()
            write_batch = db.batch()
            pending = 0
    if pending:
        write_batch.commit()

    doc_ref.update({
        "filename": safe_filename,
        "total_records": total_records,
        "processed_records": 0,
        "file_hash": digest,
        "duplicate_of": duplicate_of,
        "tables": table_names,
        "relationships": relationships,
        "quality": profile_records(headers, rows),
        "dataset_fingerprint": fingerprint_dataset(headers, rows[:5]),
        "status": SourceStatus.INSPECTING,
        "updated_at": datetime.utcnow(),
    })
    message = "File uploaded and stored for processing."
    if duplicate_of:
        message += f" Note: identical content already exists under source {duplicate_of}; entities will not be duplicated."
    if skipped_duplicates:
        message += f" Skipped {skipped_duplicates} duplicate row(s) within the file."
    return {"source_id": source_id, "total_records": total_records, "columns": headers, "tables": table_names, "duplicate_of": duplicate_of, "message": message}


@router.post("/{source_id}/schema", response_model=SourceSchema)
async def inspect_schema(source_id: str, request: Request, file: UploadFile = File(...)):
    user = _user(request)
    _check_visible(db.collection(COLLECTION_SOURCES).document(source_id).get().to_dict() if db.collection(COLLECTION_SOURCES).document(source_id).get().exists else None, user)
    lower = (file.filename or "").lower()
    if not (lower.endswith(".csv") or lower.endswith(".sql")):
        raise HTTPException(status_code=400, detail="Only CSV and SQL dump files are allowed")
    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File size exceeds {settings.max_file_size_mb}MB limit")
    try:
        text_content = content.decode("utf-8-sig")
        if lower.endswith(".sql"):
            tables, _ = parse_sql_dump(text_content)
            if not tables:
                raise ValueError("SQL dump contains no tables")
            headers = []
            for info in tables.values():
                headers.extend(c for c in info["columns"] if c not in headers)
            samples_by_header = {h: [] for h in headers}
            nullable_by_header = {h: True for h in headers}
            total_rows = sum(len(info["rows"]) for info in tables.values())
            _, flat = flatten_tables_for_ingest(tables)
            for row in flat:
                for header in headers:
                    value = str(row.get(header) or "").strip()
                    if value and len(samples_by_header[header]) < 5 and value not in samples_by_header[header]:
                        samples_by_header[header].append(value)
        else:
            reader = csv.DictReader(io.StringIO(text_content))
            headers = reader.fieldnames or []
            if not headers:
                raise ValueError("CSV has no header row")
            samples_by_header = {header: [] for header in headers}
            nullable_by_header = {header: False for header in headers}
            total_rows = 0
            for row in reader:
                total_rows += 1
                for header in headers:
                    value = (row.get(header) or "").strip()
                    if not value:
                        nullable_by_header[header] = True
                    elif len(samples_by_header[header]) < 5 and value not in samples_by_header[header]:
                        samples_by_header[header].append(value)
    except (UnicodeDecodeError, csv.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid file format: {exc}")
    columns = []
    for header in headers:
        samples = samples_by_header[header]
        inferred_type = "string"
        if samples:
            all_numeric = all(v.replace(".", "").replace("-", "").isdigit() for v in samples if v)
            if all_numeric:
                inferred_type = "number"
            elif all("@" in v for v in samples if v):
                inferred_type = "email"
            elif all(v.replace("-", "").replace(" ", "").replace("+", "").isdigit() for v in samples if v):
                inferred_type = "phone"
        columns.append(SchemaColumn(name=header, inferred_type=inferred_type, sample_values=samples, nullable=nullable_by_header[header]))
    schema = SourceSchema(source_id=source_id, columns=columns, total_columns=len(columns), total_rows=total_rows)
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    doc_ref.update({"schema": schema.model_dump(), "status": SourceStatus.MAPPING, "updated_at": datetime.utcnow()})
    return schema


@router.get("/{source_id}/mapping", response_model=MappingResponse)
async def get_mapping_suggestions(source_id: str, request: Request):
    user = _user(request)
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    source_data = doc.to_dict()
    _check_visible(source_data, user)
    if "schema" not in source_data:
        raise HTTPException(status_code=400, detail="Schema not inspected yet")
    columns = [col["name"] for col in source_data["schema"]["columns"]]
    suggested = await suggest_field_mappings(columns)
    existing = source_data.get("mappings", [])
    return MappingResponse(source_id=source_id, mappings=[FieldMapping(**m) for m in existing], suggested_mappings=suggested)


@router.post("/{source_id}/mapping", response_model=MappingResponse)
async def confirm_mapping(source_id: str, mapping_req: MappingRequest, request: Request):
    user = _user(request)
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    snap = doc_ref.get()
    if not snap.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    _check_visible(snap.to_dict(), user)
    mappings = [m.model_dump() for m in mapping_req.mappings]
    doc_ref.update({"mappings": mappings, "status": SourceStatus.MAPPING, "updated_at": datetime.utcnow()})
    return MappingResponse(source_id=source_id, mappings=mapping_req.mappings, suggested_mappings=[])


@router.get("/{source_id}/status")
async def get_source_status(source_id: str, request: Request):
    user = _user(request)
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    source_data = doc.to_dict()
    _check_visible(source_data, user)
    jobs = db.collection(COLLECTION_PROCESSING_JOBS).where("source_id", "==", source_id).order_by("created_at", direction="DESCENDING").limit(1).stream()
    job_data = None
    for job in jobs:
        jd = job.to_dict()
        if not is_visible(jd, user) and jd.get("owner_uid"):
            continue
        job_data = jd
        break
    return {"source_id": source_id, "status": source_data.get("status"), "progress": job_data.get("progress", 0) if job_data else 0, "total": job_data.get("total", 0) if job_data else 0, "processed": job_data.get("processed", 0) if job_data else 0, "errors": job_data.get("errors", []) if job_data else []}


@router.get("/{source_id}/relationships")
async def get_relationships(source_id: str, request: Request):
    """Relationship map: FK + inferred shared columns (§16 bonus)."""
    user = _user(request)
    doc = db.collection(COLLECTION_SOURCES).document(source_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    data = doc.to_dict()
    _check_visible(data, user)
    return {
        "source_id": source_id,
        "tables": data.get("tables", []),
        "relationships": data.get("relationships", []),
    }


@router.get("/{source_id}/profile")
async def get_profile(source_id: str, request: Request):
    """Schema documentation + data-quality report (§26 bonus)."""
    user = _user(request)
    doc = db.collection(COLLECTION_SOURCES).document(source_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    data = doc.to_dict()
    _check_visible(data, user)
    return {
        "source_id": source_id,
        "filename": data.get("filename"),
        "tables": data.get("tables", []),
        "schema": data.get("schema"),
        "quality": data.get("quality"),
        "dataset_fingerprint": data.get("dataset_fingerprint"),
        "duplicate_of": data.get("duplicate_of"),
        "file_hash": data.get("file_hash"),
    }


@router.get("/groups/{group_id}")
async def get_source_group(group_id: str, request: Request):
    """Multi-part dataset view: Database 1 Part 1/2/3 (§4)."""
    user = _user(request)
    docs = db.collection(COLLECTION_SOURCES).where("parent_group_id", "==", group_id).stream()
    parts = sorted(
        [Source(**d.to_dict()) for d in docs if is_visible(d.to_dict(), user)],
        key=lambda s: (s.part_number or 0),
    )
    return {
        "group_id": group_id,
        "parts": [p.model_dump() for p in parts],
        "total_records": sum(p.total_records for p in parts),
    }