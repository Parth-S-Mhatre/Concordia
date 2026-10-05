from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

from backend.config import settings
from backend.models.schemas import HealthResponse
from backend.api import sources, search, entities, processing, auth
from backend.services.auth import resolve_user
from backend.services.matching import load_indexes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print(f"Starting Concordia on {settings.app_host}:{settings.app_port}")
    try:
        await load_indexes()
    except Exception as error:
        print(f"Lookup index restore unavailable ({type(error).__name__})")
    yield
    # Shutdown
    print("Shutting down...")


app = FastAPI(
    title="Concordia — Multi-Database Entity Resolution & Unified Data Repository",
    description="Progressive Entity Enrichment Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: explicit origins plus any local host/port (localhost, 127.x, 0.0.0.0)
# so the demo works regardless of which local URL opens the frontend.
# Production domains come from FRONTEND_URLS (comma-separated).
_extra_origins = [o.strip() for o in (settings.frontend_urls or "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8080", "http://127.0.0.1:8080", *_extra_origins],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        timestamp=datetime.utcnow(),
        version="1.0.0",
    )


# Include routers (every request resolves identity; anonymous when open mode)
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(sources.router, prefix="/api/sources", tags=["sources"], dependencies=[Depends(resolve_user)])
app.include_router(search.router, prefix="/api/search", tags=["search"], dependencies=[Depends(resolve_user)])
app.include_router(entities.router, prefix="/api/entities", tags=["entities"], dependencies=[Depends(resolve_user)])
app.include_router(processing.router, prefix="/api/processing", tags=["processing"], dependencies=[Depends(resolve_user)])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )