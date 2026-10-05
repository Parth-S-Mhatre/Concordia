from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import List
import traceback
import uuid
from datetime import datetime, timezone

from backend.config import db, settings, COLLECTION_SOURCES, COLLECTION_RECORDS, COLLECTION_PROCESSING_JOBS, COLLECTION_ENTITIES, COLLECTION_INDEXES
from backend.models.schemas import FieldMapping, ProcessingJob, ProcessingStatus, Record, SourceStatus
from backend.services.cache import cache_invalidate
from backend.services.mapping import apply_field_mappings
from backend.services.normalization import normalize_record
from backend.services.matching import update_indexes, find_matching_records, persist_indexes


router = APIRouter()


def _as_aware(value):
    """Firestore returns tz-aware datetimes; datetime.utcnow() is naive.

    Mixing them raises `TypeError: can't subtract offset-naive and
    offset-aware datetimes`, so normalize everything to aware UTC first.
    """
    if value is None:
        return None
    if getattr(value, "tzinfo", None) is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@router.post("/{source_id}/start", response_model=ProcessingJob)
async def start_processing(source_id: str, background_tasks: BackgroundTasks):
    """Start the full processing pipeline for a source."""
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    
    source_data = doc.to_dict()
    
    if "mappings" not in source_data:
        raise HTTPException(status_code=400, detail="Mappings not confirmed yet")
    
    # Create processing job
    job_id = str(uuid.uuid4())[:8]
    job = ProcessingJob(
        job_id=job_id,
        source_id=source_id,
        job_type="full_pipeline",
        status=ProcessingStatus.RUNNING,
        total=source_data.get("total_records", 0),
        started_at=datetime.utcnow(),
    )
    
    db.collection(COLLECTION_PROCESSING_JOBS).document(job_id).set(job.model_dump())
    
    # Update source status
    doc_ref.update({"status": SourceStatus.CLEANING, "updated_at": datetime.utcnow()})
    
    # Start background processing
    background_tasks.add_task(run_full_pipeline, job_id, source_id, source_data)
    
    return job


async def run_full_pipeline(job_id: str, source_id: str, source_data: dict):
    """Normalize uploaded Firestore records and update the lookup indexes.

    Resumable: records are processed in source_row_id order and the job
    checkpoint records how far processing got, so a refresh/retry continues
    instead of restarting (§5: allow processing to continue after refresh).
    """
    job_ref = db.collection(COLLECTION_PROCESSING_JOBS).document(job_id)
    try:
        mappings = [FieldMapping(**mapping) for mapping in source_data.get("mappings", [])]
        job_snapshot = job_ref.get().to_dict() or {}
        start_from = int(job_snapshot.get("checkpoint", 0) or 0)
        processed = int(job_snapshot.get("processed", 0) or 0)
        matched = 0
        src = db.collection(COLLECTION_SOURCES).document(source_id).get().to_dict() or {}
        matched = int(src.get("matched_records", 0) or 0)
        batch_limit = min(max(settings.batch_size, 1), 450)

        docs = list(db.collection(COLLECTION_RECORDS).where("source_id", "==", source_id).stream())
        docs.sort(key=lambda d: (d.to_dict().get("source_row_id") or 0))
        total = len(docs)
        job_ref.update({"total": total})
        started = datetime.now(timezone.utc)

        for document in docs:
            data = document.to_dict()
            if (data.get("source_row_id") or 0) <= start_from:
                continue
            mapped = apply_field_mappings(data.get("raw_data", {}), mappings)
            normalized = normalize_record(mapped)
            for field_type, value in normalized.items():
                if field_type not in ("email", "phone", "username", "member_id") or not value.normalized_value:
                    continue
                if await find_matching_records(value.normalized_value, field_type):
                    matched += 1
                    break

            data["normalized_data"] = {key: value.model_dump() for key, value in normalized.items()}
            record = Record(**data)
            document.reference.update({"normalized_data": data["normalized_data"]})
            await update_indexes(record)
            processed += 1
            start_from = data.get("source_row_id") or start_from

            if processed % batch_limit == 0:
                job_ref.update({
                    "progress": min(95, int(processed * 95 / max(total, 1))),
                    "processed": processed,
                    "checkpoint": start_from,
                })
                db.collection(COLLECTION_SOURCES).document(source_id).update({
                    "processed_records": processed,
                    "matched_records": matched,
                    "status": SourceStatus.INDEXING,
                    "updated_at": datetime.utcnow(),
                })

        await persist_indexes()
        cache_invalidate("search:")
        cache_invalidate("suggest:")
        finished = datetime.now(timezone.utc)
        job_started = _as_aware(job_snapshot.get("started_at")) or started
        job_ref.update({
            "status": ProcessingStatus.COMPLETED,
            "progress": 100,
            "processed": processed,
            "checkpoint": start_from,
            "total": total,
            "completed_at": finished,
        })
        db.collection(COLLECTION_SOURCES).document(source_id).update({
            "status": SourceStatus.COMPLETED,
            "total_records": total,
            "processed_records": processed,
            "matched_records": matched,
            "last_processed_at": finished,
            "last_processing_seconds": (finished - job_started).total_seconds(),
            "updated_at": finished,
        })
    except Exception as error:
        traceback.print_exc()
        job_ref.update({
            "status": ProcessingStatus.FAILED,
            "errors": [f"Processing failed ({type(error).__name__}). Check backend logs."],
            "completed_at": datetime.utcnow(),
        })
        db.collection(COLLECTION_SOURCES).document(source_id).update({
            "status": SourceStatus.FAILED,
            "updated_at": datetime.utcnow(),
        })


@router.get("/jobs/{job_id}", response_model=ProcessingJob)
async def get_job_status(job_id: str):
    """Get processing job status."""
    doc = db.collection(COLLECTION_PROCESSING_JOBS).document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    return ProcessingJob(**doc.to_dict())


@router.get("/jobs", response_model=List[ProcessingJob])
async def list_jobs(source_id: str = None, limit: int = 20):
    """List processing jobs."""
    query = db.collection(COLLECTION_PROCESSING_JOBS).order_by("created_at", direction="DESCENDING").limit(limit)
    if source_id:
        query = query.where("source_id", "==", source_id)
    docs = query.stream()
    return [ProcessingJob(**doc.to_dict()) for doc in docs]


@router.post("/reprocess/{source_id}")
async def reprocess_source(source_id: str, background_tasks: BackgroundTasks):
    """Reprocess a source from scratch."""
    doc_ref = db.collection(COLLECTION_SOURCES).document(source_id)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail="Source not found")
    
    # Delete existing records
    batch = db.batch()
    for record in db.collection(COLLECTION_RECORDS).where("source_id", "==", source_id).stream():
        batch.delete(record.reference)
    batch.commit()
    
    # Reset source stats
    doc_ref.update({
        "processed_records": 0,
        "matched_records": 0,
        "new_entities": 0,
        "enriched_entities": 0,
        "status": SourceStatus.CLEANING,
        "updated_at": datetime.utcnow(),
    })
    
    # Start new processing
    return await start_processing(source_id, background_tasks)


@router.post("/jobs/{job_id}/resume")
async def resume_job(job_id: str, background_tasks: BackgroundTasks):
    """Resume an interrupted job from its checkpoint (§5)."""
    doc = db.collection(COLLECTION_PROCESSING_JOBS).document(job_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Job not found")
    job = doc.to_dict()
    if job.get("status") == ProcessingStatus.COMPLETED:
        return ProcessingJob(**job)
    source_id = job["source_id"]
    source = db.collection(COLLECTION_SOURCES).document(source_id).get()
    if not source.exists:
        raise HTTPException(status_code=404, detail="Source not found")
    db.collection(COLLECTION_PROCESSING_JOBS).document(job_id).update(
        {"status": ProcessingStatus.RUNNING, "updated_at": datetime.utcnow()}
    )
    background_tasks.add_task(run_full_pipeline, job_id, source_id, source.to_dict())
    return ProcessingJob(**db.collection(COLLECTION_PROCESSING_JOBS).document(job_id).get().to_dict())


@router.get("/stats/global")
async def get_global_stats():
    """Persistent import + matching statistics (§20)."""
    sources = list(db.collection(COLLECTION_SOURCES).stream())
    jobs = list(db.collection(COLLECTION_PROCESSING_JOBS).stream())
    entities = list(db.collection(COLLECTION_ENTITIES).stream())

    total_tables = sum(len((s.to_dict().get("tables") or []) or [1]) if s.to_dict().get("tables") else 1 for s in sources)
    total_records = sum(s.to_dict().get("total_records", 0) for s in sources)
    processed = sum(s.to_dict().get("processed_records", 0) for s in sources)
    matched = sum(s.to_dict().get("matched_records", 0) for s in sources)
    failures = sum(1 for j in jobs if j.to_dict().get("status") == ProcessingStatus.FAILED)
    multi_source = sum(1 for e in entities if len(e.to_dict().get("source_ids", [])) > 1)
    last_processed = None
    for s in sources:
        ts = s.to_dict().get("last_processed_at") or s.to_dict().get("updated_at")
        if ts and (last_processed is None or ts > last_processed):
            last_processed = ts

    return {
        "total_databases": len(sources),
        "total_tables": total_tables,
        "total_records": total_records,
        "records_processed": processed,
        "records_matched": matched,
        "new_entities_created": len(entities),
        "entities_enriched": multi_source,
        "duplicate_records_detected": sum(
            (s.to_dict().get("quality") or {}).get("duplicate_rows_in_sample", 0) for s in sources
        ),
        "unresolved_records": max(total_records - matched, 0),
        "processing_failures": failures,
        "last_processed_time": last_processed,
    }