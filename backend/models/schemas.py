from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, EmailStr
from enum import Enum


class SourceStatus(str, Enum):
    UPLOADED = "UPLOADED"
    INSPECTING = "INSPECTING"
    MAPPING = "MAPPING"
    CLEANING = "CLEANING"
    INDEXING = "INDEXING"
    MATCHING = "MATCHING"
    ENRICHING = "ENRICHING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SourceBase(BaseModel):
    name: str
    filename: str
    type: str = "csv"
    parent_group_id: Optional[str] = None
    part_number: Optional[int] = None


class SourceCreate(SourceBase):
    pass


class SourceUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[SourceStatus] = None
    total_records: Optional[int] = None
    processed_records: Optional[int] = None
    matched_records: Optional[int] = None
    new_entities: Optional[int] = None
    enriched_entities: Optional[int] = None


class Source(SourceBase):
    source_id: str
    status: SourceStatus = SourceStatus.UPLOADED
    total_records: int = 0
    processed_records: int = 0
    matched_records: int = 0
    new_entities: int = 0
    enriched_entities: int = 0
    file_hash: Optional[str] = None
    duplicate_of: Optional[str] = None
    tables: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class SchemaColumn(BaseModel):
    name: str
    inferred_type: str
    sample_values: List[str] = []
    nullable: bool = True


class SourceSchema(BaseModel):
    source_id: str
    columns: List[SchemaColumn]
    total_columns: int
    total_rows: int


class FieldMapping(BaseModel):
    source_column: str
    canonical_field: str
    confidence: float = 1.0
    is_reviewed: bool = False


class MappingRequest(BaseModel):
    mappings: List[FieldMapping]


class MappingResponse(BaseModel):
    source_id: str
    mappings: List[FieldMapping]
    suggested_mappings: List[FieldMapping]


# Canonical fields
CANONICAL_FIELDS = [
    "email",
    "phone",
    "username",
    "member_id",
    "name",
    "address",
    "company",
]


class NormalizedValue(BaseModel):
    original_value: str
    normalized_value: str
    field_type: str


class RecordBase(BaseModel):
    source_id: str
    source_row_id: int
    raw_data: Dict[str, Any]


class RecordCreate(RecordBase):
    normalized_data: Dict[str, NormalizedValue] = {}


class Record(RecordBase):
    record_id: str
    normalized_data: Dict[str, NormalizedValue] = {}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class EntityField(BaseModel):
    value: str
    source_id: str
    source_record_id: str
    source_field: str
    original_value: str
    confidence: float = 1.0


class EntityBase(BaseModel):
    name: Optional[EntityField] = None
    email: Optional[EntityField] = None
    phone: Optional[EntityField] = None
    username: Optional[EntityField] = None
    member_id: Optional[EntityField] = None
    address: Optional[EntityField] = None
    company: Optional[EntityField] = None


class EntityCreate(EntityBase):
    pass


class Entity(EntityBase):
    entity_id: str
    source_ids: List[str] = []
    record_ids: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class ProcessingJobBase(BaseModel):
    source_id: str
    job_type: str


class ProcessingJobCreate(ProcessingJobBase):
    pass


class ProcessingJob(ProcessingJobBase):
    job_id: str
    status: ProcessingStatus = ProcessingStatus.PENDING
    progress: int = 0
    total: int = 0
    processed: int = 0
    checkpoint: int = 0
    errors: List[str] = []
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class EnrichmentStep(BaseModel):
    step: int
    identifier_type: str
    identifier_value: str
    source_id: str
    source_name: str
    discovered_fields: Dict[str, str]


class SearchResponse(BaseModel):
    entity: Optional[Entity] = None
    sources: List[str] = []
    enrichment_steps: List[EnrichmentStep] = []
    matched_records_count: int = 0


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = "1.0.0"


class TableRelationship(BaseModel):
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    kind: str = "inferred_shared_column"


class SourceGroup(BaseModel):
    group_id: str
    source_ids: List[str] = []
    total_records: int = 0