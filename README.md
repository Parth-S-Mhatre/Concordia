# Entity Resolution Platform

Multi-Database Entity Resolution & Unified Data Repository with Progressive Entity Enrichment.

## Quick Start

### Prerequisites
- Python 3.10+
- Firebase project with Firestore enabled
- (Optional) NVIDIA NIM API key for AI field mapping

### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Environment Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp ../.env.example ../.env
# Edit .env with your credentials
```

Required environment variables:
- `FIREBASE_PROJECT_ID` - Your Firebase project ID
- `FIREBASE_CLIENT_EMAIL` - Service account client email
- `FIREBASE_PRIVATE_KEY` - Service account private key (with \n for newlines)
- `NVIDIA_NIM_API_KEY` - (Optional) NVIDIA NIM API key for AI mapping

### Run Backend

```bash
cd ..
backend/venv/bin/uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Backend will be available at `http://localhost:8000`
API docs at `http://localhost:8000/docs`

### Run Frontend

Serve the frontend directory with any static file server:

```bash
cd frontend
python -m http.server 8080
```

Frontend will be available at `http://localhost:8080`

Or use VS Code Live Server extension.

### Load Demo Data

1. Open frontend at `http://localhost:8080`
2. Go to **Sources** tab
3. Click **Upload CSV** and upload the 4 demo files from `data/demo/`:
   - `database_a.csv`
   - `database_b.csv`
   - `database_c.csv`
   - `database_d.csv`
4. For each source, go to **Mapping** tab, select the source, click **Load Mappings**, review, then **Confirm & Start Processing**
5. Go to **Search** tab and search for `john@example.com` to see progressive enrichment

## Demo Scenario

The demo data is designed to demonstrate progressive entity enrichment:

```
Search: john@example.com
  ↓ Database A: John Doe, 9876543210
  ↓ Discover phone: 9876543210
  ↓ Database B: Mumbai (address)
  ↓ Database C: johndoe (username), ABC Pvt Ltd (company)
  ↓ Database D: MEM1042 (member_id)
  ↓ MASTER ENTITY: John Doe with all 7 fields from 4 sources
```

## Project Structure

```
entity-resolution-platform/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Configuration & Firebase init
│   ├── requirements.txt
│   ├── api/
│   │   ├── sources.py       # Source CRUD, upload, schema, mapping
│   │   ├── search.py        # Entity search with enrichment
│   │   ├── entities.py      # Master entity management
│   │   └── processing.py    # Background processing jobs
│   ├── services/
│   │   ├── ingestion.py     # CSV batch processing
│   │   ├── mapping.py       # Field mapping (NIM + rules)
│   │   ├── normalization.py # Value normalization
│   │   ├── matching.py      # Indexing & matching engine
│   │   ├── enrichment.py    # Progressive enrichment (BFS)
│   │   └── nim.py           # NVIDIA NIM client
│   └── models/
│       └── schemas.py       # Pydantic models
├── frontend/
│   ├── index.html
│   ├── css/styles.css
│   └── js/
│       ├── api.js           # API client
│       └── app.js           # Application logic
├── data/demo/               # Demo CSV files
├── docs/ARCHITECTURE.md
├── .env.example
├── .gitignore
└── README.md
```

## API Endpoints

### Sources
- `POST /api/sources` - Create source
- `GET /api/sources` - List sources
- `GET /api/sources/{id}` - Get source
- `PATCH /api/sources/{id}` - Update source
- `DELETE /api/sources/{id}` - Delete source
- `POST /api/sources/{id}/upload` - Upload CSV
- `POST /api/sources/{id}/schema` - Inspect schema
- `GET /api/sources/{id}/mapping` - Get mapping suggestions
- `POST /api/sources/{id}/mapping` - Confirm mappings
- `GET /api/sources/{id}/status` - Get processing status

### Search
- `POST /api/search` - Search entity (progressive enrichment)
- `GET /api/search/suggestions` - Get search suggestions

### Entities
- `GET /api/entities` - List entities
- `GET /api/entities/{id}` - Get entity
- `GET /api/entities/{id}/traceability` - Source traceability
- `GET /api/entities/{id}/enrichment-path` - Enrichment path
- `GET /api/entities/stats/summary` - Dashboard stats

### Processing
- `POST /api/processing/{source_id}/start` - Start processing
- `GET /api/processing/jobs/{job_id}` - Job status
- `GET /api/processing/jobs` - List jobs
- `POST /api/processing/reprocess/{source_id}` - Reprocess

## Architecture Highlights

- **Progressive Entity Enrichment**: BFS traversal discovering identifiers across datasets
- **Source Traceability**: Every field traced to original source record
- **Batch Processing**: Configurable batch size (default 1000) for large datasets
- **NIM Integration**: AI-powered field mapping with deterministic fallback
- **In-Memory Indexes**: Email, phone, username, member_id lookup indexes
- **Master Entities**: Deduplicated unified entities with provenance

## Security

- NVIDIA NIM API key never exposed to frontend
- Strict CORS configuration
- Input validation on all endpoints
- File size and type validation
- No secrets in logs or git

## Authentication (Firebase)

Sign-in is optional by default so the evaluator demo link stays open.

### One-time Firebase setup

1. Firebase console → **Authentication → Sign-in method** → enable **Email/Password**.
2. **Project settings → General** → copy the **Web API Key** into `.env` as `FIREBASE_API_KEY`.
3. Grant the seeder permission (only needed once): GCP console → **IAM** →
   find `FIREBASE_CLIENT_EMAIL` → add role **Firebase Authentication Admin**.
4. Seed the demo admin account:
   ```bash
   backend/venv/bin/python backend/seed_admin.py
   ```
   Default credentials (change via `DEMO_ADMIN_EMAIL` / `DEMO_ADMIN_PASSWORD`):
   - Email: `admin@concordia.demo`
   - Password: `Concordia-Admin-2026`

### Interview demo

- Open the workspace → **Sign in** (top right) → **Fill demo admin credentials** → **Sign in**.
- The user chip shows the email with an `ADMIN` badge; source deletion is admin-only.
- Optional: `REQUIRE_AUTH=true` in `.env` + restart backend — the workspace then shows a login gate and guests are blocked.

## Deployment (Netlify + Render)

Recommended: **Netlify** for the static frontend, **Render** for the FastAPI backend.

### Backend on Render

1. Push the repo to GitHub. Render → **New → Web Service** → connect the repo.
2. Build command: `pip install -r backend/requirements.txt`
3. Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Add every variable from `.env` as environment variables (paste the private key with real newlines).
5. Note the service URL, e.g. `https://concordia-api.onrender.com`.

### Frontend on Netlify

1. Netlify → **Add new site → Import from Git** → same repo, publish directory: `frontend` (no build command).
2. In `frontend/_redirects`, replace `YOUR-RENDER-APP` with your Render service name.
3. The app auto-uses relative `/api` in production (proxied to Render, no CORS issues).
4. Back on Render, set `FRONTEND_URLS=https://YOUR-SITE.netlify.app` and redeploy.
5. Seed the demo admin once via Render → **Shell**: `python backend/seed_admin.py`.

Free-tier note: Render sleeps after inactivity — the first search after idle takes ~30s to wake. Firestore data persists regardless.

## License

MIT