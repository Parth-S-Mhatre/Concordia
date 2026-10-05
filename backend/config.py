from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
import firebase_admin
from firebase_admin import credentials, firestore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    # NVIDIA NIM
    nvidia_nim_api_key: str = Field(default="", alias="NVIDIA_NIM_API_KEY")
    
    # Firebase
    firebase_project_id: str = Field(default="", alias="FIREBASE_PROJECT_ID")
    firebase_client_email: str = Field(default="", alias="FIREBASE_CLIENT_EMAIL")
    firebase_private_key: str = Field(default="", alias="FIREBASE_PRIVATE_KEY")
    
    # App
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    debug: bool = Field(default=True, alias="DEBUG")
    
    # Processing
    batch_size: int = Field(default=1000, alias="BATCH_SIZE")
    max_file_size_mb: int = Field(default=50, alias="MAX_FILE_SIZE_MB")

    # Caching (§21) — optional Redis, falls back to in-memory
    redis_url: str = Field(default="", alias="REDIS_URL")

    # CORS: extra production origins, comma-separated
    # e.g. FRONTEND_URLS=https://concordia.netlify.app
    frontend_urls: str = Field(default="", alias="FRONTEND_URLS")

    # Auth — Firebase Authentication (Email/Password).
    # REQUIRE_AUTH=false keeps the evaluator demo link open (default).
    # Set true to gate the API behind sign-in.
    require_auth: bool = Field(default=False, alias="REQUIRE_AUTH")
    # Web API key (Firebase console → Project settings → General).
    # Only used to serve the public client config; the private key above
    # stays server-side and verifies ID tokens.
    firebase_api_key: str = Field(default="", alias="FIREBASE_API_KEY")
    firebase_auth_domain: str = Field(default="", alias="FIREBASE_AUTH_DOMAIN")
    # Demo admin seeded by backend/seed_admin.py for interviews/testing.
    demo_admin_email: str = Field(default="admin@concordia.demo", alias="DEMO_ADMIN_EMAIL")
    demo_admin_password: str = Field(default="Concordia-Admin-2026", alias="DEMO_ADMIN_PASSWORD")
    
    class Config:
        env_file = PROJECT_ROOT / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()


def initialize_firebase() -> firestore.Client:
    """Initialize Firebase Admin SDK on first use and return Firestore client."""
    if not firebase_admin._apps:
        if settings.firebase_project_id and settings.firebase_client_email and settings.firebase_private_key:
            private_key = settings.firebase_private_key.replace("\\n", "\n")
            
            cred_dict = {
                "type": "service_account",
                "project_id": settings.firebase_project_id,
                "client_email": settings.firebase_client_email,
                "private_key": private_key,
                "token_uri": "https://oauth2.googleapis.com/token",
            }
            cred = credentials.Certificate(cred_dict)
        else:
            cred = credentials.ApplicationDefault()
        
        firebase_admin.initialize_app(cred, {
            "projectId": settings.firebase_project_id,
        })
    
    return firestore.client()


class FirestoreProxy:
    """Keep app imports and health checks independent from Firebase availability."""

    def __getattr__(self, name):
        return getattr(initialize_firebase(), name)


db = FirestoreProxy()


# Collection names
COLLECTION_SOURCES = "sources"
COLLECTION_RECORDS = "records"
COLLECTION_ENTITIES = "entities"
COLLECTION_PROCESSING_JOBS = "processing_jobs"
COLLECTION_INDEXES = "indexes"