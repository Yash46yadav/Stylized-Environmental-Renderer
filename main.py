"""
Phase 2: FastAPI HTTP Wrapper
==============================
Exposes the Phase 1 engine over HTTP so any client (browser, Postman, curl)
can POST a photo and get a stylized image back in seconds.

Key FastAPI concepts used here
-------------------------------
• @app.post / @app.get        – route decorators (like Flask's @app.route)
• UploadFile                  – FastAPI's file-upload abstraction
• FileResponse                – stream a file back to the client
• Depends()                   – dependency injection (e.g. shared config)
• HTTPException               – clean JSON error responses
• Background cleanup          – delete temp files after the response is sent

Run with:
    uvicorn main:app --reload --port 8000

Test with curl:
    curl -X POST http://localhost:8000/api/v1/render \
         -F "file=@/path/to/your/photo.jpg" \
         --output stylized.jpg

API surface
-----------
POST /api/v1/render          – upload image, get stylized image back
GET  /api/v1/health          – server health check
GET  /api/v1/docs            – auto-generated Swagger UI (built into FastAPI!)
"""

import os
import uuid
import time
import tempfile
import traceback
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ─── Import the engine we built in Phase 1 ───────────────────────
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "phase1"))
from engine import stylize

# ─────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────
app = FastAPI(
    title="Stylized Environmental Renderer",
    description="""
Upload any photo and receive a painterly, hand-drawn-style version.

Pipeline: **Bilateral Filter → K-Means Colour Quantization → Edge Detection → Composite**
    """,
    version="1.0.0",
)

# Allow all CORS origins for local development.
# In production you'd whitelist your frontend domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temp directory for output images (cleaned up after response is sent)
TEMP_DIR = Path(tempfile.gettempdir()) / "stylized_renderer"
TEMP_DIR.mkdir(exist_ok=True)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
MAX_SIZE_MB   = 15


# ─────────────────────────────────────────────
# HELPER – TEMP FILE CLEANUP
# ─────────────────────────────────────────────
def _delete_file(path: Path):
    """Background task: delete the temp output file after the response is sent."""
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass  # Non-fatal; OS will clean up eventually


# ─────────────────────────────────────────────
# ROUTE: Health check
# ─────────────────────────────────────────────
@app.get("/api/v1/health", tags=["System"])
async def health():
    """
    Quick liveness probe.
    Returns 200 OK so load-balancers / orchestration know the server is up.
    """
    return {"status": "ok", "service": "stylized-renderer", "version": "1.0.0"}


# ─────────────────────────────────────────────
# ROUTE: Main render endpoint
# ─────────────────────────────────────────────
@app.post("/api/v1/render", tags=["Render"])
async def render_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="JPEG/PNG photo to stylize"),

    # Optional query params to tune the algorithm
    k_colors: int   = Query(default=12,  ge=4,   le=32,  description="K-Means palette size"),
    passes:   int   = Query(default=3,   ge=1,   le=6,   description="Bilateral filter passes"),
    edges:    str   = Query(default="canny",              description="Edge method: canny | sobel"),
    canny_low:  int = Query(default=50,  ge=10,  le=200, description="Canny low threshold"),
    canny_high: int = Query(default=150, ge=50,  le=400, description="Canny high threshold"),
):
    """
    **Main endpoint**: upload an image → receive a stylized version.

    The response is a raw image file (JPEG).
    You can open it directly in a browser, or pipe it to a file with curl.

    Parameters (query string)
    --------------------------
    - `k_colors`   : Colour palette size. Fewer = more cartoon-like. Default 12.
    - `passes`     : Bilateral filter iterations. More = smoother. Default 3.
    - `edges`      : 'canny' for clean lines, 'sobel' for rough artistic lines.
    - `canny_low`  : Lower hysteresis threshold for Canny. Default 50.
    - `canny_high` : Upper hysteresis threshold for Canny. Default 150.
    """

    # ── 1. Validate MIME type ─────────────────────────────────────
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{file.content_type}'. "
                   f"Accepted: {', '.join(ALLOWED_TYPES)}"
        )

    # ── 2. Read upload bytes ──────────────────────────────────────
    raw_bytes = await file.read()

    if len(raw_bytes) > MAX_SIZE_MB * 1_000_000:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(raw_bytes)//1_000_000} MB). Max {MAX_SIZE_MB} MB."
        )

    # ── 3. Decode into OpenCV array ───────────────────────────────
    nparr  = np.frombuffer(raw_bytes, np.uint8)
    image  = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        raise HTTPException(status_code=400, detail="Could not decode image data.")

    # ── 4. Validate edge method ───────────────────────────────────
    if edges not in ("canny", "sobel"):
        raise HTTPException(status_code=422,
                            detail=f"edges must be 'canny' or 'sobel', got '{edges}'")

    # ── 5. Run the pipeline ───────────────────────────────────────
    t0 = time.time()
    try:
        result = stylize(
            image,
            k_colors=k_colors,
            bilateral_passes=passes,
            edge_method=edges,
            canny_low=canny_low,
            canny_high=canny_high,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")

    elapsed = time.time() - t0

    # ── 6. Save to temp file ──────────────────────────────────────
    out_name = f"{uuid.uuid4().hex}_stylized.jpg"
    out_path = TEMP_DIR / out_name
    cv2.imwrite(str(out_path), result, [cv2.IMWRITE_JPEG_QUALITY, 95])

    # Schedule cleanup: file deleted AFTER FastAPI finishes streaming it
    background_tasks.add_task(_delete_file, out_path)

    # ── 7. Return the file ────────────────────────────────────────
    return FileResponse(
        path=str(out_path),
        media_type="image/jpeg",
        filename="stylized.jpg",
        headers={
            "X-Processing-Time": f"{elapsed:.3f}s",
            "X-K-Colors": str(k_colors),
            "X-Edge-Method": edges,
        }
    )


# ─────────────────────────────────────────────
# ROUTE: Parameter info
# ─────────────────────────────────────────────
@app.get("/api/v1/parameters", tags=["Render"])
async def get_parameters():
    """Returns documented parameter ranges for the render endpoint."""
    return {
        "k_colors":   {"min": 4,  "max": 32,  "default": 12,  "description": "Palette colour count"},
        "passes":     {"min": 1,  "max": 6,   "default": 3,   "description": "Bilateral filter passes"},
        "edges":      {"options": ["canny", "sobel"], "default": "canny"},
        "canny_low":  {"min": 10, "max": 200, "default": 50},
        "canny_high": {"min": 50, "max": 400, "default": 150},
    }
