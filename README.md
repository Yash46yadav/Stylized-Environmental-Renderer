# Stylized Environmental Renderer
### Full-Stack Build Guide — All 5 Phases

---

## Project Map

```
stylized-renderer/
├── phase1/          ← Core Python engine (OpenCV)
│   ├── engine.py
│   └── test_engine.py
├── phase2/          ← FastAPI HTTP wrapper (sync)
│   ├── main.py
│   └── test_api.py
├── phase3/          ← Celery async architecture
│   ├── worker.py
│   └── async_main.py
├── phase4/          ← S3 storage + PostgreSQL
│   ├── database.py
│   ├── storage.py
│   └── worker_v2.py
└── phase5/          ← React frontend
    └── index.html
```

---

## Phase 1 · Core Algorithm Engine

### What you're building
A pure Python image-processing pipeline. No web, no server. Just input image → output image.

### Setup
```bash
# Create a virtual environment (keeps your project's packages isolated from global Python)
python -m venv venv
source venv/bin/activate   # Mac/Linux
venv\Scripts\activate      # Windows

# Install dependencies
pip install opencv-python numpy
```

### Run it
```bash
cd phase1
python engine.py --input your_photo.jpg --output result.jpg

# Tune parameters:
python engine.py --input photo.jpg --output result.jpg \
  --colors 8    \   # fewer = more cartoon-like
  --passes 4    \   # more = smoother flat areas
  --edges sobel     # 'sobel' for rougher artistic lines
```

### Run the automated test
```bash
python test_engine.py
# Generates a synthetic landscape, runs the full pipeline, saves each stage
# All 14 tests should pass
```

### Key concepts explained

**Bilateral Filter**
Normal Gaussian blur blurs everything including edges. Bilateral filter
blurs smooth areas but leaves high-contrast edges (object boundaries) sharp.
Two Gaussians: one for spatial proximity, one for colour similarity.

**K-Means Clustering**
Groups all pixel colours into K clusters. Every pixel is repainted with
its cluster's average colour. A 24-bit photo has 16 million possible colours;
K=12 reduces it to exactly 12. This is what gives the "flat painted" look.

**Canny Edge Detection**
1. Gaussian blur to remove noise
2. Sobel gradient to find magnitude and direction
3. Non-maximum suppression — keep only local gradient peaks
4. Hysteresis thresholding — keep strong edges, keep weak ones only if
   connected to strong ones. Result: thin, clean outlines.

---

## Phase 2 · FastAPI HTTP Wrapper

### What you're building
Wrap the engine in an HTTP API. Anyone can now POST an image and receive
a stylized one — from the browser, Postman, or curl.

### Setup
```bash
pip install fastapi uvicorn python-multipart
```

### Run it
```bash
cd phase2
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000/docs for the auto-generated Swagger UI.

### Test with curl
```bash
curl -X POST http://localhost:8000/api/v1/render \
     -F "file=@/path/to/photo.jpg" \
     --output stylized.jpg

# With custom parameters:
curl -X POST "http://localhost:8000/api/v1/render?k_colors=8&edges=sobel" \
     -F "file=@photo.jpg" --output stylized.jpg
```

### Test with Postman
1. New Request → POST → http://localhost:8000/api/v1/render
2. Body tab → form-data
3. Key: `file` | Type: File | Value: select your photo
4. Send → Save response as file

### Key concepts

**FastAPI vs Flask**
FastAPI is async-native, auto-generates OpenAPI docs, validates parameters
with Pydantic types, and is significantly faster under load.

**UploadFile**
FastAPI's abstraction for multipart form uploads. The `await file.read()`
call reads all bytes asynchronously — it doesn't block the event loop.

**FileResponse**
Streams a file back to the client efficiently. Combined with
BackgroundTasks, it deletes the temp file AFTER the stream finishes.

**Run the automated test:**
```bash
cd phase2
python test_api.py
# Starts server in background thread, fires HTTP requests, checks responses
```

---

## Phase 3 · Asynchronous Architecture

### The problem with Phase 2
Phase 2 is synchronous — if 10 users upload simultaneously, all 10 threads
are stuck running OpenCV for 3–5 seconds each. Server saturates and times out.

### The solution: Task Queue
```
User uploads image
       │
FastAPI returns {"task_id": "abc123"}  ← immediate, < 5ms
       │
Redis queue ──► Celery worker runs stylize() in background (3–5s)
       │
User polls GET /status/abc123 every 2s until state == "SUCCESS"
```

### Setup
```bash
# Install Redis (Mac)
brew install redis && redis-server

# Install Redis (Ubuntu/Debian)
sudo apt install redis-server && sudo systemctl start redis

# Install Redis (Windows)
# Download from https://github.com/microsoftarchive/redis/releases

# Install Python packages
pip install celery redis
```

### Run it (3 terminals)
```bash
# Terminal 1: Redis
redis-server

# Terminal 2: Celery worker
cd phase3
celery -A worker worker --loglevel=info --concurrency=4

# Terminal 3: FastAPI
uvicorn async_main:app --reload --port 8000
```

### Test it
```bash
# Submit a job
curl -X POST http://localhost:8000/api/v1/render \
     -F "file=@photo.jpg"
# Returns: {"task_id": "abc123...", "poll_url": "/api/v1/status/abc123..."}

# Poll for completion
curl http://localhost:8000/api/v1/status/abc123...
# Returns: {"state": "PENDING"} → {"state": "STARTED"} → {"state": "SUCCESS", "result_b64": "..."}
```

### Key concepts

**Redis** is an in-memory key-value store used here as:
- **Broker**: the queue where tasks wait (Celery puts/takes tasks)
- **Backend**: where task results are stored (keyed by task_id)

**Celery** is a Python task queue. `@celery_app.task` turns any function
into a distributed task. `.apply_async()` sends it to Redis without waiting.
`AsyncResult(task_id)` queries Redis for the task's current state.

**Celery task states**: PENDING → STARTED → SUCCESS / FAILURE

**Why base64?** Redis stores JSON. JSON can't contain raw binary bytes.
We encode binary image data as a base64 ASCII string for transport through Redis.

---

## Phase 4 · Cloud Storage & Database

### What you're building
Replace temp files with permanent S3 storage. Record every render job
in PostgreSQL for history, analytics, and user dashboards.

### Setup

**Local dev (SQLite + local disk — no cloud needed):**
```bash
pip install sqlalchemy psycopg2-binary boto3
# SQLite works out of the box, no server needed
# USE_LOCAL_STORAGE=true (default) saves images to /tmp/stylized_storage/
```

**Production (PostgreSQL + AWS S3):**
```bash
# 1. Create PostgreSQL database
createdb stylized_renderer

# 2. Create S3 bucket in AWS console
#    - Name: your-renderer-bucket
#    - Region: us-east-1
#    - Block all public access: optional

# 3. Set environment variables
export DATABASE_URL="postgresql://user:pass@localhost:5432/stylized_renderer"
export AWS_ACCESS_KEY_ID="your_key"
export AWS_SECRET_ACCESS_KEY="your_secret"
export AWS_DEFAULT_REGION="us-east-1"
export S3_BUCKET_NAME="your-renderer-bucket"
export USE_LOCAL_STORAGE="false"
```

### Database schema (renders table)
```
id               UUID         Primary key
task_id          VARCHAR      Celery task ID (unique)
user_id          VARCHAR      Who submitted the job
original_url     TEXT         S3 URL of the uploaded photo
stylized_url     TEXT         S3 URL of the processed output
status           VARCHAR      queued | processing | success | failed
k_colors         INTEGER      Pipeline parameter (for audit/replay)
edge_method      VARCHAR      Pipeline parameter
bilateral_passes INTEGER      Pipeline parameter
processing_s     FLOAT        Wall-clock seconds for stylize()
error_message    TEXT         Failure details if status=failed
created_at       TIMESTAMP    Job submission time (UTC)
completed_at     TIMESTAMP    Job completion time (UTC)
```

### Key concepts

**SQLAlchemy ORM** maps Python classes to DB tables. You define a class,
inherit from Base, and SQLAlchemy generates the CREATE TABLE SQL for you.
`db.add(render)`, `db.commit()`, `db.query(Render).filter_by(...)` — no raw SQL needed.

**Sessions** are the "unit of work". A session tracks changes and flushes
them to the database on commit. Always close the session when done.

**S3 bucket** stores images as "objects" at path-like "keys".
Structure: `originals/uuid_original.jpg`, `stylized/uuid_stylized.jpg`
The S3 URL is permanent and can be stored in the DB, served to clients,
used in emails, CDN-cached, etc.

---

## Phase 5 · Frontend UI

### What you're building
A React SPA (Single Page Application) with:
- Drag-and-drop image upload
- Pipeline parameter sliders
- Loading state with live pipeline progress steps
- Side-by-side before/after comparison
- Download button

### Setup (React version)
```bash
# Create a new React project
npm create vite@latest render-studio -- --template react
cd render-studio
npm install
npm run dev  # http://localhost:5173
```

### Or use the standalone HTML
The `phase5/index.html` is a complete no-build frontend.
Just open it in a browser — no Node.js required.

```bash
# To serve it locally (needed for API fetch to work):
cd phase5
python -m http.server 9000
# Open http://localhost:9000
```

### Connect to the backend
Edit `index.html` line 1:
```js
const API_BASE = 'http://localhost:8000';  // your FastAPI server
const ASYNC_MODE = false;  // true for Phase 3+ with Celery
```

### Key concepts

**Polling** — the frontend calls `GET /status/{task_id}` every 2 seconds
using `setInterval()`. When state === 'SUCCESS', it clears the interval
and displays the result. This is simpler than WebSockets for a first build.

**FormData** — the browser-native way to send multipart form data
(files + fields) in a POST request. FastAPI's `UploadFile` reads it.

**Blob + createObjectURL** — when the API returns a raw image (sync mode),
`response.blob()` captures it. `URL.createObjectURL(blob)` creates a
local `blob://...` URL that an `<img>` tag can display without any upload.

**Base64 decode** — when the API returns `result_b64`, JavaScript decodes it
with `atob()`, builds a Uint8Array of bytes, wraps it in a Blob, and creates
an object URL. Same result, different transport.

---

## Running the Full Stack (All Phases)

```bash
# Terminal 1 — Redis
redis-server

# Terminal 2 — Celery Worker
cd stylized-renderer/phase4
celery -A worker_v2 worker --loglevel=info

# Terminal 3 — FastAPI
cd stylized-renderer/phase3
uvicorn async_main:app --reload --port 8000

# Terminal 4 — Frontend
cd stylized-renderer/phase5
python -m http.server 9000
# Open http://localhost:9000
```

---

## Test Results Summary

| Phase | Tests | Status |
|-------|-------|--------|
| 1 · Engine    | 14/14 | ✅ All pass |
| 2 · API       |  9/9  | ✅ All pass |
| 3 · Worker    | 10/10 | ✅ All pass |
| 4 · DB+S3     | 13/13 | ✅ All pass |
| **Total**     | **46/46** | **✅** |

---

## What to Build Next

- **Authentication** — JWT tokens, user accounts, render history dashboard
- **WebSocket progress** — replace polling with real-time push notifications
- **Style presets** — save/load named parameter sets ("Studio Ghibli", "Moebius")
- **Batch processing** — upload a folder, get all images stylized
- **GPU acceleration** — OpenCV supports CUDA; massive speedup on NVIDIA GPUs
- **Model-based stylization** — replace K-Means with a neural style transfer model
#   S t y l i z e d - E n v i r o n m e n t a l - R e n d e r e r  
 