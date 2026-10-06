# RENDERX — Complete Project Guide
### Everything you need to understand, explain, and defend this project

---

## TABLE OF CONTENTS
1. [What We Built & Why](#what-we-built)
2. [The Build Journey — File by File](#build-journey)
3. [How Every File Connects](#connections)
4. [Every Skill Used — Simple Definitions](#skills)
5. [Interview Prep — How to Explain It](#interview-prep)
6. [Common Interview Questions + Answers](#questions)
7. [Architecture Deep Dive](#architecture)
8. [Things That Could Go Wrong + How We Handle Them](#error-handling)

---

## 1. WHAT WE BUILT & WHY

### The Problem
Indie game developers and digital artists need stylized artwork (cartoon/painterly look)
but can't afford concept artists. They have real photos but need them to look hand-drawn.

### The Solution
A full-stack web application where a user:
1. Uploads a regular photo
2. The system processes it through an image pipeline
3. Gets back a painterly, cartoon-style version

### Why It's Impressive (for Resume)
- Combines computer vision algorithms + backend engineering + cloud + frontend
- Shows you can build a production-grade system end to end
- Demonstrates knowledge of async architecture (senior-level concept)
- Uses 8+ technologies working together

---

## 2. THE BUILD JOURNEY — FILE BY FILE

We built this in 5 phases. Here is the exact order files were created and why.

---

### PHASE 1 — The Core Algorithm Engine

#### File 1: `engine.py`
**Created first because:** Everything depends on this. No API, no frontend, no database
matters until the core image processing actually works.

**What it does:**
Transforms a photo into a stylized image using 4 steps:

```
Step 1: Bilateral Filter    → Smooths colors, keeps edges sharp
Step 2: K-Means Clustering  → Reduces photo to N flat colors (cartoon look)
Step 3: Color Grading       → Adds warm cinematic tone
Step 4: Edge Detection      → Draws black ink outlines
Step 5: Composite           → Combines color + outlines into final image
```

**How to run it locally:**
```bash
python engine.py --input photo.jpg --output result.jpg --colors 12
```

**Key functions inside engine.py:**
- `apply_bilateral_filter()` — smooths but keeps edges
- `apply_kmeans_quantization()` — reduces colors
- `apply_color_grade()` — cinematic warm tones
- `apply_edge_detection()` — draws outlines
- `composite()` — merges layers
- `stylize()` — master function that calls all the above in order

---

### PHASE 2 — The API Wrapper

#### File 2: `main.py` (FastAPI server — synchronous)
**Created second because:** Once the engine works, we need to expose it over HTTP
so a browser or any client can use it.

**What it does:**
- Creates an HTTP server on port 8000
- Accepts image uploads via POST request
- Passes the image to `engine.py`'s `stylize()` function
- Returns the processed image as a file download

**Key endpoints:**
```
GET  /api/v1/health      → "is the server alive?"
POST /api/v1/render      → "here's my photo, give me stylized version"
GET  /api/v1/parameters  → "what settings can I pass?"
```

**How main.py connects to engine.py:**
```python
# Inside main.py
from engine import stylize          # imports the function we wrote in Phase 1
result = stylize(image, k_colors=12)  # calls it directly
```

**Problem with this approach:**
If 10 users upload at once, all 10 are waiting. Server slows down → Phase 3 fixes this.

---

### PHASE 3 — Asynchronous Architecture

#### File 3: `worker.py` (Celery task)
**Created third because:** We need to move heavy processing OUT of the web server
into a background worker.

**What it does:**
- Defines a Celery "task" — think of it as a function that runs in the background
- Receives image data from Redis queue
- Runs the `stylize()` function
- Stores the result back in Redis

**Key concept:**
```python
@celery_app.task(bind=True, name="tasks.process_image")
def process_image_task(self, image_b64, k_colors=12, ...):
    # This runs in background, not in the web server
    result = stylize(image)
    return {"result_b64": base64_of_result}
```

**How worker.py connects to engine.py:**
```python
from engine import stylize  # same import, now called from background worker
```

#### File 4: `async_main.py` (Async FastAPI server)
**Created fourth because:** The API needs to change its behavior — instead of waiting
for the result, it should immediately return a task ID.

**What it does:**
- Accepts image upload
- Immediately returns `{"task_id": "abc123"}` (in milliseconds)
- Client polls `GET /status/abc123` every 2 seconds
- When done, returns the stylized image

**How async_main.py connects to worker.py:**
```python
from worker import celery_app, process_image_task

# Sends task to Redis queue — does NOT wait for it
task = process_image_task.apply_async(kwargs={...})
return {"task_id": task.id}  # returns immediately
```

---

### PHASE 4 — Cloud Storage & Database

#### File 5: `database.py` (SQLAlchemy ORM)
**Created fifth because:** We need to permanently record every render job.

**What it does:**
- Defines the `Render` Python class that maps to a PostgreSQL table
- Every render job gets a row: task_id, user_id, image URLs, status, timing
- Provides `init_db()` to create tables and `get_db()` for sessions

**The renders table structure:**
```
id             → unique identifier for this render
task_id        → Celery task ID (links to Redis)
user_id        → who submitted it
original_url   → S3 path of uploaded photo
stylized_url   → S3 path of processed result
status         → queued / processing / success / failed
k_colors       → what settings were used
processing_s   → how long it took
created_at     → when submitted
completed_at   → when finished
```

**How database.py connects to everything:**
- `worker_v2.py` imports `SessionLocal` and `Render` to write records
- `async_main.py` could import it to read render history

#### File 6: `storage.py` (S3 abstraction)
**Created sixth because:** We need permanent storage for images beyond temp files.

**What it does:**
- Wraps AWS S3 operations in a clean class
- In local dev: saves to `C:\tmp\stylized_storage\` on disk
- In production: uploads to AWS S3 bucket
- Returns a URL for every uploaded image

**How storage.py connects:**
```python
# Inside worker_v2.py
from storage import storage

key, url = storage.upload_image(image_bytes, folder="originals")
# url = "file://C:\tmp\stylized_storage\originals\abc.jpg" (local)
# url = "https://bucket.s3.amazonaws.com/originals/abc.jpg" (production)
```

#### File 7: `worker_v2.py` (Updated Celery worker)
**Created seventh because:** The original worker just processed images.
Now it also needs to save to S3 and write to the database.

**What it does (full flow):**
```
1. Receives task from Redis queue
2. Creates a Render record in PostgreSQL (status: processing)
3. Uploads original image to S3
4. Runs stylize() pipeline
5. Uploads result to S3
6. Updates Render record (status: success, adds URLs, timing)
7. Returns result for Redis storage
```

**How worker_v2.py connects to everything:**
```python
from engine   import stylize          # Phase 1
from storage  import storage          # Phase 4 (S3)
from database import SessionLocal, Render  # Phase 4 (PostgreSQL)
```
This file is the most connected — it talks to ALL other layers.

---

### PHASE 5 — The Frontend

#### File 8: `frontend.html` (Single-page React-style UI)
**Created last because:** The frontend is only useful once the full backend works.

**What it does:**
- Single HTML file with embedded CSS + JavaScript (no build step needed)
- Drag-and-drop image upload
- Sliders for all pipeline parameters
- Sends POST request to `/api/v1/render`
- If ASYNC_MODE=true: polls `/api/v1/status/{task_id}` every 2 seconds
- Shows side-by-side before/after comparison
- Download button for the stylized image

**How frontend.html connects to the backend:**
```javascript
const API_BASE = 'http://localhost:8000';  // points to async_main.py

// Upload image
fetch(`${API_BASE}/api/v1/render`, { method: 'POST', body: formData })
  .then(res => res.json())
  .then(data => pollStatus(data.task_id));  // start polling

// Poll for result
fetch(`${API_BASE}/api/v1/status/${taskId}`)
  .then(res => res.json())
  .then(data => {
    if(data.state === 'SUCCESS') showImage(data.result_b64);
  });
```

---

## 3. HOW EVERY FILE CONNECTS

```
frontend.html
    │
    │  HTTP POST /api/v1/render (image upload)
    ▼
async_main.py  ──────────────────────────────────────────────────────┐
    │                                                                 │
    │  task = process_image_task.apply_async()                       │
    │  return {task_id}                                               │
    ▼                                                              (polls)
 Redis Queue                                                    frontend.html
    │                                                         GET /status/{id}
    │  worker picks up task
    ▼
worker_v2.py
    │
    ├──► engine.py         → runs the image pipeline
    │        (bilateral → kmeans → grade → edges → composite)
    │
    ├──► storage.py        → uploads images to S3 / local disk
    │        (original + stylized)
    │
    └──► database.py       → writes Render record to PostgreSQL
             (id, task_id, urls, status, timing)
```

**Redis serves two roles:**
- **Broker**: queue where tasks wait to be picked up
- **Backend**: storage where task results are saved after completion

---

## 4. EVERY SKILL USED — SIMPLE DEFINITIONS

### COMPUTER VISION / IMAGE PROCESSING

#### Bilateral Filter
**What it is:** A blur that is smart — it blurs flat areas but leaves edges sharp.
Normal blur makes everything soft including edges. Bilateral blur looks at
both how close pixels are AND how similar in color they are before blending.

**Where used:** `engine.py → apply_bilateral_filter()`

**Simple analogy:** Like a painter who blends colors in the sky but keeps
a sharp line where the sky meets a mountain.

---

#### K-Means Clustering
**What it is:** A machine learning algorithm that groups similar things together.
For images: groups all pixel colors into K clusters, then repaints every pixel
with its cluster's average color.

**Where used:** `engine.py → apply_kmeans_quantization()`

**Simple analogy:** Imagine sorting millions of paint colors into just 12 buckets.
Every pixel gets repainted with its bucket's color.

**The algorithm:**
```
1. Pick K random colors as starting "centroids"
2. Assign every pixel to its nearest centroid
3. Recalculate each centroid as the average of its pixels
4. Repeat until colors stop changing
```

---

#### Canny Edge Detection
**What it is:** An algorithm that finds boundaries between objects in an image.
It finds where pixel brightness changes sharply (= an edge).

**Where used:** `engine.py → apply_edge_detection()`

**Steps:**
```
1. Gaussian blur → removes noise
2. Sobel gradient → finds how much brightness changes at every pixel
3. Non-maximum suppression → thins edges to 1 pixel wide
4. Hysteresis thresholding → keeps strong edges, discards weak ones
```

---

#### Sobel Operator
**What it is:** Detects edges by computing the gradient (rate of change) of
brightness in X and Y directions. Less refined than Canny — gives rougher,
more artistic-looking lines.

**Where used:** `engine.py → apply_edge_detection(method='sobel')`

---

#### Color Grading
**What it is:** Adjusting saturation, contrast, and color tone of an image
to achieve a specific mood. Like Instagram filters but custom-coded.

**Where used:** `engine.py → apply_color_grade()`

**Techniques:**
- HSV color space manipulation (Hue, Saturation, Value)
- `cv2.convertScaleAbs(alpha, beta)` — contrast and brightness
- Channel splitting and adding warm tint to R channel

---

### PYTHON BACKEND

#### FastAPI
**What it is:** A modern Python web framework for building APIs.
Faster than Flask, automatically generates documentation, validates
data types automatically, and supports async natively.

**Where used:** `main.py`, `async_main.py`

**Key features we used:**
- `@app.post("/api/v1/render")` — route decorator
- `UploadFile` — handles file uploads
- `FileResponse` — streams files back to client
- `HTTPException` — returns clean error responses
- `BackgroundTasks` — cleanup after response sent
- Auto Swagger UI at `/docs` — free interactive testing page

---

#### Celery
**What it is:** A Python library for running tasks in the background,
separate from your web server. When processing takes 5-10 seconds,
you don't want the web server frozen.

**Where used:** `worker.py`, `worker_v2.py`, `async_main.py`

**Key concepts:**
- `@celery_app.task` — turns a function into a background task
- `.apply_async()` — sends task to the queue without waiting
- `AsyncResult(task_id)` — checks status of a running task
- Task states: PENDING → STARTED → SUCCESS / FAILURE

---

#### SQLAlchemy ORM
**What it is:** ORM = Object Relational Mapper. Lets you work with
a database using Python classes instead of writing raw SQL.

**Where used:** `database.py`, `worker_v2.py`

**Without ORM (raw SQL):**
```sql
INSERT INTO renders (id, task_id, status) VALUES ('abc', 'xyz', 'queued');
```

**With ORM (SQLAlchemy):**
```python
render = Render(id='abc', task_id='xyz', status='queued')
db.add(render)
db.commit()
```

---

#### Pydantic (via FastAPI)
**What it is:** Data validation library. FastAPI uses it automatically
to validate query parameters and request bodies.

**Where used:** FastAPI route parameters in `main.py`, `async_main.py`

**Example:** `k_colors: int = Query(default=12, ge=4, le=32)` — FastAPI
automatically rejects values below 4 or above 32 and returns a 422 error.

---

### DATABASES & STORAGE

#### PostgreSQL
**What it is:** The most popular open-source relational database.
Stores structured data in tables with rows and columns.

**Where used:** Stores the `renders` table — one row per render job.

**Why PostgreSQL over SQLite:**
- Handles multiple users simultaneously (concurrent writes)
- Better for production
- Industry standard

---

#### Redis
**What it is:** An in-memory key-value store — like a super-fast dictionary
stored in RAM instead of on disk.

**Where used:** As Celery's broker AND backend

**Two roles in our project:**
1. **Message Broker**: holds the queue of tasks waiting to be processed
2. **Result Backend**: stores task results (the processed image as base64)

**Why Redis is fast:** Data lives in RAM, not on disk. Reads are ~100x faster.

---

#### AWS S3 (Simple Storage Service)
**What it is:** Amazon's cloud file storage. Like Google Drive for developers —
you upload files and get a permanent URL back.

**Where used:** `storage.py` — stores original and stylized images permanently

**Key concepts:**
- **Bucket**: top-level container (like a folder on the internet)
- **Key**: the file path within the bucket
- **Presigned URL**: temporary link to a private file

**We use local disk in dev** via `USE_LOCAL_STORAGE=true` — same interface,
saves to `C:\tmp\stylized_storage\` instead.

---

### ASYNC & CONCURRENCY

#### Async/Await (Python)
**What it is:** A way to write code that doesn't block while waiting.
Instead of waiting for a response, Python can handle other requests.

**Where used:** All route functions in `async_main.py`

```python
async def render_image(file: UploadFile):
    raw_bytes = await file.read()  # doesn't block the server
    # server can handle other requests while this reads
```

---

#### Task Queue Pattern
**What it is:** Instead of doing slow work immediately, put it in a queue
and let workers handle it in the background.

**Where used:** The entire Phase 3 architecture

```
Client sends request → Server returns task_id instantly
                    → Worker processes image in background
Client polls status → Gets result when ready
```

**Why this matters in interviews:** This is exactly how Gmail processes
attachments, how YouTube transcodes videos, how Uber assigns drivers.
It's a fundamental backend pattern.

---

#### Base64 Encoding
**What it is:** A way to convert binary data (images, files) into
text characters. Necessary because Redis stores JSON (text), not binary.

**Where used:** `worker.py`, `worker_v2.py`, `frontend.html`

```
Binary image bytes → Base64 string → Stored in Redis → Decoded back to bytes
```

---

### WEB & API CONCEPTS

#### REST API
**What it is:** A standard way to design HTTP APIs using standard verbs:
- GET — retrieve data
- POST — send/create data
- PUT — update data
- DELETE — remove data

**Where used:** All endpoints in `main.py` and `async_main.py`

---

#### CORS (Cross-Origin Resource Sharing)
**What it is:** Browser security rule that blocks JavaScript from calling
an API on a different domain. We need to explicitly allow it.

**Where used:** `CORSMiddleware` in both API files

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"])
# "*" = allow ALL origins (fine for dev, restrict in production)
```

---

#### Multipart Form Data
**What it is:** The format used to upload files over HTTP.
It's how `<input type="file">` sends data to a server.

**Where used:** `UploadFile` in FastAPI, `FormData` in JavaScript

---

#### Polling
**What it is:** Repeatedly asking "is it done yet?" every few seconds.
Simpler than WebSockets for a first build.

**Where used:** `frontend.html` — `setInterval` calls `/status/{id}` every 2s

```javascript
poll = setInterval(async () => {
  const status = await fetch(`/api/v1/status/${taskId}`);
  if(status.state === 'SUCCESS') { clearInterval(poll); showResult(); }
}, 2000);
```

---

#### Environment Variables
**What it is:** Configuration values stored outside your code so you
don't hardcode secrets like passwords and API keys.

**Where used:** `database.py`, `storage.py`, `worker.py`

```python
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///dev.db")
# Uses env var in production, falls back to SQLite in development
```

---

### FRONTEND

#### Drag and Drop API
**What it is:** Browser-native events for detecting when files are
dragged over an element and dropped.

**Where used:** `frontend.html`

```javascript
dropEl.addEventListener('dragover', e => { e.preventDefault(); });
dropEl.addEventListener('drop', e => { setFile(e.dataTransfer.files[0]); });
```

---

#### Fetch API
**What it is:** Modern JavaScript way to make HTTP requests from the browser.
Replaced XMLHttpRequest (XHR).

**Where used:** `frontend.html` — all API calls

---

#### CSS Custom Properties (Variables)
**What it is:** Variables in CSS that can be reused everywhere.
Change one value, everything updates.

**Where used:** `:root { --p1: #7c6dfa; }` in `frontend.html`

---

#### Glassmorphism
**What it is:** UI trend of frosted-glass effect using `backdrop-filter: blur()`
and semi-transparent backgrounds.

**Where used:** All cards and header in `frontend.html`

---

## 5. INTERVIEW PREP — HOW TO EXPLAIN IT

### 60-Second Elevator Pitch

*"I built a full-stack image stylization engine called RENDERX. The core is a
computer vision pipeline in Python using OpenCV — it applies bilateral filtering
to smooth colors while preserving edges, then uses K-Means clustering to
quantize the image to a flat color palette, adds Canny edge detection for ink
outlines, and composites them into a painterly result.*

*I wrapped that in a FastAPI REST API and then refactored to an async architecture
using Celery and Redis — so image uploads return immediately with a task ID,
and a background worker handles the heavy processing. The frontend polls a
status endpoint every 2 seconds until the result is ready.*

*I added PostgreSQL to track render metadata and S3 for permanent image storage.
The whole stack is: Python, OpenCV, FastAPI, Celery, Redis, PostgreSQL,
SQLAlchemy, AWS S3, and a vanilla JS frontend."*

---

### How to Walk Through It in an Interview

**Start with the problem:**
> "Indie game developers need stylized artwork but can't afford concept artists.
> So I built a tool that automatically transforms photos into hand-drawn-style images."

**Explain the algorithm:**
> "The core is a 5-step pipeline. First, bilateral filtering — which is like
> Gaussian blur but it preserves edges. Then K-Means clustering to reduce the
> palette to maybe 12 flat colors. Then Canny edge detection for the outlines.
> Finally I composite the color layer with the edges."

**Explain the architecture evolution:**
> "I started synchronous — upload image, wait 5 seconds, get result. Fine for one
> user. But for concurrency I refactored to a task queue pattern using Celery
> and Redis. Now the API returns a task ID instantly and a background worker
> handles the processing. Classic producer-consumer pattern."

**Explain why each tech choice:**
> - FastAPI: async-native, automatic OpenAPI docs, faster than Flask
> - Celery: standard Python task queue, integrates with Redis natively
> - Redis: in-memory so very fast for queue operations, built-in result storage
> - PostgreSQL: production-grade, handles concurrent writes unlike SQLite
> - S3: permanent URL-based storage, industry standard for binary files

---

## 6. COMMON INTERVIEW QUESTIONS + ANSWERS

---

**Q: Why did you use K-Means for color quantization instead of just reducing bit depth?**

A: Bit depth reduction (like posterization) splits the color range uniformly —
for example, dividing 0-255 into 8 buckets regardless of what colors actually
exist in the image. K-Means is adaptive — it finds where the actual colors
cluster in the image and places centroids there. For a photo of a sunset,
K-Means will allocate more centroids to the orange-red range because
that's where most pixels live. The result looks much more natural.

---

**Q: What happens if two users upload at the same time in your async system?**

A: They each get their own task ID immediately. Celery has a worker pool
(we set concurrency=2) so it can process 2 images simultaneously. Additional
tasks wait in the Redis queue. The client-side polling is per-task-ID, so
each user independently polls their own status. No user sees another user's result.

---

**Q: Why not just use WebSockets instead of polling?**

A: Polling was the right trade-off for this project. WebSockets require a
persistent connection — more infrastructure complexity, harder to scale
horizontally, and the client needs to handle reconnections. Polling is
stateless, simple to implement, and works fine when the result comes
in 5-10 seconds. If I were handling real-time updates under 1 second,
I'd use WebSockets. Polling at 2-second intervals is perfectly acceptable here.

---

**Q: How does base64 encoding work and why do you use it?**

A: Base64 takes binary data (bytes like 0x89 0xFF 0x4A) and encodes them
as printable ASCII characters using a 64-character alphabet (A-Z, a-z, 0-9, +, /).
Every 3 bytes become 4 ASCII characters — about 33% size increase.
We use it because Redis stores task results as JSON, and JSON can't contain
raw binary. Base64 makes binary JSON-safe. On the frontend, `atob()` decodes
it back to binary to create an image Blob.

---

**Q: What is the bilateral filter doing mathematically?**

A: A standard Gaussian blur computes a weighted average of neighboring pixels
where the weight only depends on spatial distance. A bilateral filter adds
a second weight based on color similarity. So the final weight for a neighbor
pixel is: `spatial_weight × color_similarity_weight`. Pixels that are both
close AND similar in color get high weight. Pixels across a color boundary
get near-zero weight even if they're spatially close. This preserves edges.

---

**Q: How would you scale this to 1000 concurrent users?**

A: Several steps:
1. Increase Celery worker concurrency and run multiple worker instances
2. Move Redis to a cluster (Redis Sentinel or ElastiCache)
3. Move PostgreSQL to a managed service (RDS) with read replicas
4. Put FastAPI behind a load balancer (Nginx or AWS ALB)
5. Add a CDN (CloudFront) in front of S3 so stylized images are served from edge
6. Consider GPU instances for the OpenCV processing — massive speedup

---

**Q: Why FastAPI over Flask?**

A: Three main reasons:
1. FastAPI is async-native — Flask is synchronous by default
2. FastAPI auto-generates OpenAPI/Swagger docs from your code
3. FastAPI uses Pydantic for automatic request validation — less boilerplate
4. Benchmarks show FastAPI is significantly faster than Flask under load

---

**Q: What is the difference between Celery broker and backend?**

A: The broker is the queue — where tasks go when they're submitted and where
workers pick them up from. The backend is where results are stored after
a task completes. We use Redis for both. When you call `.apply_async()`,
the task goes into the broker queue. When the worker finishes, it saves
the return value to the backend. When you call `AsyncResult(task_id).result`,
Celery fetches it from the backend.

---

**Q: How do you handle failures in the pipeline?**

A: Multiple layers:
1. Input validation in FastAPI — wrong file type → 415 error before processing
2. `try/except` in the Celery task — if `stylize()` throws, we catch it,
   update the DB record to `status: failed` with the error message, and re-raise
   so Celery marks the task as FAILURE
3. Client-side — the frontend checks for `state === 'FAILURE'` and shows
   an error message
4. The DB record always has a `completed_at` timestamp and `error_message`
   field for audit

---

**Q: Why store pipeline parameters in the database?**

A: Three reasons:
1. **Reproducibility** — if a user asks "can you regenerate that render?",
   we know exactly what settings produced it
2. **Analytics** — you can query which k_colors value is most popular,
   which produces fastest results, etc.
3. **Debugging** — if a user reports bad output, you can see the exact
   parameters that caused it

---

**Q: What is an ORM and why use one?**

A: ORM = Object Relational Mapper. It maps Python classes to database tables,
so you work with Python objects instead of writing SQL strings. Benefits:
1. Type safety — the ORM knows column types
2. SQL injection prevention — parameters are always escaped
3. Database portability — switching from SQLite to PostgreSQL requires
   changing only the connection string
4. Cleaner code — `db.query(Render).filter_by(status='success')` reads
   better than raw SQL

---

**Q: How would you add user authentication to this?**

A: I'd add JWT (JSON Web Tokens):
1. User logs in → server returns a signed JWT token
2. Client includes token in every request header: `Authorization: Bearer <token>`
3. FastAPI middleware validates the token on protected routes
4. The `user_id` in the Render table (currently NULL) would be populated
   from the JWT payload
I'd use `python-jose` for JWT and `passlib` for password hashing.

---

**Q: Explain the data flow for a single render end to end.**

A:
```
1. User selects photo in browser
2. JavaScript sends POST /api/v1/render with FormData
3. FastAPI reads the file bytes, base64-encodes them
4. Calls process_and_store_task.apply_async() → task goes to Redis queue
5. FastAPI immediately returns {"task_id": "abc123"} to client
6. Client starts polling GET /api/v1/status/abc123 every 2 seconds
7. Celery worker picks up task from Redis queue
8. Worker creates a Render record in PostgreSQL (status: processing)
9. Worker uploads original image to S3, gets URL
10. Worker calls stylize() — 5-step pipeline runs, ~5-8 seconds
11. Worker uploads stylized image to S3, gets URL
12. Worker updates PostgreSQL record (status: success, URLs, timing)
13. Worker returns result dict → Celery saves it to Redis backend
14. Next poll: FastAPI reads AsyncResult from Redis → state=SUCCESS
15. FastAPI returns result_b64 to client
16. Client decodes base64 → creates Blob → displays in <img> tag
17. User clicks Download → browser saves the file
```

---

## 7. ARCHITECTURE DEEP DIVE

### Why This Architecture Pattern Matters

This is called the **Producer-Consumer** or **Task Queue** pattern.
It's used everywhere in real production systems:

| Company | Where They Use It |
|---------|-------------------|
| YouTube | Video transcoding after upload |
| Instagram | Image resizing for thumbnails |
| Uber | Matching riders to drivers |
| Gmail | Processing email attachments |
| Netflix | Encoding videos to multiple resolutions |

By using it in your project, you're demonstrating you understand
how production systems work at scale.

---

### The Three-Layer Architecture

```
Presentation Layer:   frontend.html
                      ↕ HTTP
Application Layer:    async_main.py (FastAPI)
                      ↕ Redis Queue
Processing Layer:     worker_v2.py (Celery)
                      ↕             ↕             ↕
                   engine.py    storage.py    database.py
                  (Algorithm)    (S3/Files)  (PostgreSQL)
```

Each layer only knows about the layer directly below it.
This separation makes the system:
- **Testable** — test each layer independently
- **Scalable** — scale each layer independently
- **Maintainable** — change one layer without breaking others

---

## 8. THINGS THAT COULD GO WRONG + HOW WE HANDLE THEM

| Scenario | What Happens | How We Handle It |
|----------|-------------|-----------------|
| User uploads a 50MB file | FastAPI rejects before processing | `MAX_SIZE_MB = 15` check + 413 error |
| User uploads a PDF | Rejected immediately | MIME type whitelist check + 415 error |
| K-Means takes forever | Large images take longer | Bilateral filter reduces before k-means |
| Redis goes down | Tasks can't be queued | Worker shows connection error clearly |
| PostgreSQL is down | DB write fails | Try/except in worker, task still completes |
| Celery worker crashes mid-task | `task_acks_late=True` | Task returns to queue, retried by another worker |
| Two workers process same task | Prevented by design | Redis queue is atomic — each task claimed once |
| S3 upload fails | Error caught, DB marked failed | Try/except in worker_v2.py |
| Bad image data | cv2.imdecode returns None | Explicit None check + ValueError raised |

---

## QUICK REFERENCE — TECHNOLOGIES AT A GLANCE

| Tech | Role | File |
|------|------|------|
| Python | Core language | All `.py` files |
| OpenCV | Image processing | `engine.py` |
| NumPy | Array math for pixels | `engine.py` |
| FastAPI | HTTP API framework | `main.py`, `async_main.py` |
| Uvicorn | ASGI server to run FastAPI | Run command |
| Celery | Background task queue | `worker.py`, `worker_v2.py` |
| Redis | Message broker + result store | Config in workers |
| SQLAlchemy | ORM for database | `database.py` |
| psycopg | PostgreSQL driver | `database.py` |
| PostgreSQL | Relational database | `database.py` |
| boto3 | AWS SDK (S3 access) | `storage.py` |
| AWS S3 | Cloud file storage | `storage.py` |
| HTML/CSS/JS | Frontend UI | `frontend.html` |
| Fetch API | HTTP calls from browser | `frontend.html` |
| Base64 | Binary-to-text encoding | `worker.py`, `frontend.html` |

---

## FINAL TIPS FOR THE INTERVIEW

1. **Draw the architecture on a whiteboard if offered.** Show the
   boxes: Browser → FastAPI → Redis → Celery → Engine/S3/PostgreSQL.
   Interviewers love candidates who can visualize systems.

2. **Lead with the problem, not the tech.** Start with "indie devs can't
   afford concept artists" before mentioning OpenCV.

3. **Explain why you chose async.** Don't just say you used Celery —
   say "image processing is CPU-bound and takes 5-8 seconds, so a
   synchronous API would block under concurrent load."

4. **Own the tradeoffs.** If asked "why not WebSockets?" say "polling
   at 2 seconds is simpler to implement and perfectly adequate for
   5-10 second processing times. I'd use WebSockets if I needed
   sub-second updates."

5. **Know your numbers.** Processing time: ~5-8s. File limit: 15MB.
   K-Means range: 4-32 colors. Celery concurrency: 2 workers.
   Polling interval: 2 seconds.

6. **Mention what you'd add next.** Auth (JWT), rate limiting,
   GPU acceleration, WebSocket progress, style presets. Shows
   you think beyond the assignment.
