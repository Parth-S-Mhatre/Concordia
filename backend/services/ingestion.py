import csv
import io
import uuid
from datetime import datetime
from typing import List, Dict, Any
from backend.config import db, settings, COLLECTION_RECORDS, COLLECTION_SOURCES
from backend.models.schemas import Record, NormalizedValue
from backend.services.mapping import apply_field_mappings
from backend.services.normalization import normalize_record
from backend.services.matching import update_indexes


async def process_csv_in_batches(source_id: str, csv_content: str, mappings: List[Dict], batch_size: int = None):
    """Process CSV content in batches."""
    if batch_size is None:
        batch_size = settings.batch_size
    
    reader = csv.DictReader(io.StringIO(csv_content))
    rows = list(reader)
    
    total = len(rows)
    processed = 0
    errors = []
    
    # Update source status
    db.collection(COLLECTION_SOURCES).document(source_id).update({
        "status": "CLEANING",
        "updated_at": datetime.utcnow(),
    })
    
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        batch_records = []
        
        for row_idx, row in enumerate(batch):
            try:
                # Apply mappings
                mapped = apply_field_mappings(row, [type('obj', (object,), m) for m in mappings])
                
                # Normalize
                normalized = normalize_record(mapped)
                
                # Create record
                record_id = str(uuid.uuid4())[:12]
                record = Record(
                    record_id=record_id,
                    source_id=source_id,
                    source_row_id=i + row_idx,
                    raw_data=row,
                    normalized_data=normalized,
                )
                
                batch_records.append(record)
                
            except Exception as e:
                errors.append(f"Row {i + row_idx}: {str(e)}")
        
        # Batch write to Firestore
        if batch_records:
            batch_write = db.batch()
            for record in batch_records:
                doc_ref = db.collection(COLLECTION_RECORDS).document(record.record_id)
                batch_write.set(doc_ref, record.model_dump())
            batch_write.commit()
            
            # Update indexes
            for record in batch_records:
                await update_indexes(record)
        
        processed += len(batch)
        
        # Update progress
        db.collection(COLLECTION_SOURCES).document(source_id).update({
            "processed_records": processed,
            "updated_at": datetime.utcnow(),
        })
    
    # Final update
    db.collection(COLLECTION_SOURCES).document(source_id).update({
        "status": "INDEXING",
        "processed_records": total,
        "updated_at": datetime.utcnow(),
    })
    
    return {"processed": processed, "errors": errors}


async def ingest_source_data(source_id: str, file_content: bytes, mappings: List[Dict]):
    """Main ingestion entry point."""
    try:
        text_content = file_content.decode("utf-8")
        result = await process_csv_in_batches(source_id, text_content, mappings)
        return result
    except Exception as e:
        db.collection(COLLECTION_SOURCES).document(source_id).update({
            "status": "FAILED",
            "updated_at": datetime.utcnow(),
        })
        raise