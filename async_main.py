# """
# Phase 3: Asynchronous FastAPI Server
# ======================================
# Changed from Phase 2:
#   - POST /render  → no longer blocks; immediately returns {"task_id": "..."}
#   - GET  /status/{task_id} → polls Redis for task state & result

# The heavy lifting is now done by the Celery worker in worker.py.

# Run order:
#   1. redis-server              (message broker)
#   2. celery -A worker worker   (background processor)
#   3. uvicorn async_main:app    (this file)
# """

# import os
# import sys
# import base64
# import uuid
# from pathlib import Path

# import numpy as np
# from fastapi import FastAPI, File, UploadFile, HTTPException, Query
# from fastapi.responses import JSONResponse, Response
# from fastapi.middleware.cors import CORSMiddleware
# from celery.result import AsyncResult

# # Import Celery app + task
# sys.path.insert(0, os.path.dirname(__file__))
# # from worker import celery_app, process_image_task
# from worker_v2 import celery_app, process_and_store_task

# ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
# MAX_SIZE_MB   = 15

# app = FastAPI(
#     title="Stylized Renderer – Async API",
#     description="Fire-and-forget image stylization via Celery task queue.",
#     version="2.0.0",
# )

# app.add_middleware(CORSMiddleware, allow_origins=["*"],
#                    allow_methods=["*"], allow_headers=["*"])


# # ─────────────────────────────────────────────
# # POST /api/v1/render  →  immediate task_id
# # ─────────────────────────────────────────────
# @app.post("/api/v1/render", tags=["Render"])
# async def render_image(
#     file: UploadFile = File(...),
#     k_colors:   int = Query(default=12,  ge=4,  le=32),
#     passes:     int = Query(default=3,   ge=1,  le=6),
#     edges:      str = Query(default="canny"),
#     canny_low:  int = Query(default=50,  ge=10, le=200),
#     canny_high: int = Query(default=150, ge=50, le=400),
# ):
#     """
#     Accept an image upload and immediately return a task_id.
#     The image is queued for processing — the client should poll /status/{task_id}.

#     Response: {"task_id": "abc123...", "status": "queued"}
#     """
#     if file.content_type not in ALLOWED_TYPES:
#         raise HTTPException(415, detail=f"Unsupported type: {file.content_type}")

#     raw_bytes = await file.read()

#     if len(raw_bytes) > MAX_SIZE_MB * 1_000_000:
#         raise HTTPException(413, detail=f"File too large. Max {MAX_SIZE_MB} MB.")

#     # ── Encode image as base64 for Redis transport ────────────────
#     # Redis (via Celery) only stores JSON, not raw bytes.
#     # Base64 converts binary → ASCII string → JSON-safe.
#     image_b64 = base64.b64encode(raw_bytes).decode("utf-8")

#     # ── Dispatch task to Celery (non-blocking) ────────────────────
#     task = process_and_store_task.apply_async(
#         kwargs=dict(
#             render_id=str(uuid.uuid4()),
#             image_b64=image_b64,
#             k_colors=k_colors,
#             passes=passes,
#             edges=edges,
#             canny_low=canny_low,
#             canny_high=canny_high,
#         )
#     )

#     return JSONResponse({
#         "task_id": task.id,
#         "status":  "queued",
#         "message": "Image queued for processing. Poll /api/v1/status/{task_id}.",
#         "poll_url": f"/api/v1/status/{task.id}",
#     })


# # ─────────────────────────────────────────────
# # GET /api/v1/status/{task_id}
# # ─────────────────────────────────────────────
# @app.get("/api/v1/status/{task_id}", tags=["Render"])
# async def get_task_status(task_id: str):
#     """
#     Poll this endpoint every 2 seconds until state == 'SUCCESS'.

#     Possible states
#     ---------------
#     PENDING  : Task hasn't started yet (sitting in queue)
#     STARTED  : Worker has picked it up and is processing
#     SUCCESS  : Done! The result contains the stylized image as base64.
#     FAILURE  : Something went wrong. The result contains error details.

#     On SUCCESS, the response includes:
#         result_b64  : Base64-encoded JPEG — decode and display in <img> or save to disk
#         processing_s: Seconds the pipeline took
#     """
#     async_result = AsyncResult(task_id, app=celery_app)

#     state = async_result.state

#     if state == "PENDING":
#         return {"task_id": task_id, "state": "PENDING", "message": "Waiting in queue…"}

#     if state == "STARTED":
#         meta = async_result.info or {}
#         return {"task_id": task_id, "state": "STARTED",
#                 "progress": meta.get("progress", "Processing…")}

#     if state == "SUCCESS":
#         result = async_result.result
#         return {
#             "task_id":      task_id,
#             "state":        "SUCCESS",
#             "result_b64":   result["result_b64"],
#             "processing_s": result["processing_s"],
#         }

#     if state == "FAILURE":
#         return JSONResponse(
#             status_code=500,
#             content={"task_id": task_id, "state": "FAILURE",
#                      "error": str(async_result.result)}
#         )

#     # Any other state (RETRY, REVOKED, etc.)
#     return {"task_id": task_id, "state": state}


# @app.get("/api/v1/health", tags=["System"])
# async def health():
#     return {"status": "ok", "version": "2.0.0", "mode": "async-celery"}

"""
Phase 4: Asynchronous FastAPI Server (with mode selector)
============================================================
POST /render  -> returns {"task_id": "..."} immediately
GET  /status/{task_id} -> polls Redis for task state & result

mode query param:
  auto      - best-effort face detection, falls back to landscape, then classic
  face      - force the anime PORTRAIT model (use for photos of people)
  neural    - force the anime LANDSCAPE model (use for scenery/nature)
  classic   - force the plain OpenCV pipeline (sliders apply here only)

Run order:
  1. redis-server (or Windows service)
  2. celery -A worker_v2 worker --loglevel=info --concurrency=2 -P threads
  3. uvicorn async_main:app --reload --port 8000
"""

import os
import sys
import base64
import uuid
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from celery.result import AsyncResult

sys.path.insert(0, os.path.dirname(__file__))
from worker_v2 import celery_app, process_and_store_task

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}
MAX_SIZE_MB   = 15

app = FastAPI(
    title="Stylized Renderer - Async API",
    description="Fire-and-forget image stylization via Celery task queue.",
    version="4.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


@app.post("/api/v1/render", tags=["Render"])
async def render_image(
    file: UploadFile = File(...),
    k_colors:   int = Query(default=12,  ge=4,  le=32),
    passes:     int = Query(default=3,   ge=1,  le=6),
    edges:      str = Query(default="canny"),
    canny_low:  int = Query(default=50,  ge=10, le=200),
    canny_high: int = Query(default=150, ge=50, le=400),
    mode:       str = Query(default="auto", regex="^(auto|face|neural|classic)$"),
    variant:    str = Query(default="H50",  regex="^(H40|H50|H64)$"),
):
    """
    Accept an image upload and immediately return a task_id.
    The image is queued for processing - the client should poll /status/{task_id}.
    """
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(415, detail=f"Unsupported type: {file.content_type}")

    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_SIZE_MB * 1_000_000:
        raise HTTPException(413, detail=f"File too large. Max {MAX_SIZE_MB} MB.")

    image_b64 = base64.b64encode(raw_bytes).decode("utf-8")

    task = process_and_store_task.apply_async(
        kwargs=dict(
            render_id  = str(uuid.uuid4()),
            image_b64  = image_b64,
            k_colors   = k_colors,
            passes     = passes,
            edges      = edges,
            canny_low  = canny_low,
            canny_high = canny_high,
            mode       = mode,
            variant    = variant,
        )
    )

    return JSONResponse({
        "task_id": task.id,
        "status":  "queued",
        "mode":    mode,
        "poll_url": f"/api/v1/status/{task.id}",
    })


@app.get("/api/v1/status/{task_id}", tags=["Render"])
async def get_task_status(task_id: str):
    async_result = AsyncResult(task_id, app=celery_app)
    state = async_result.state

    if state == "PENDING":
        return {"task_id": task_id, "state": "PENDING", "message": "Waiting in queue..."}

    if state == "STARTED":
        meta = async_result.info or {}
        return {"task_id": task_id, "state": "STARTED",
                "progress": meta.get("progress", "Processing...")}

    if state == "SUCCESS":
        result = async_result.result
        return {
            "task_id":      task_id,
            "state":        "SUCCESS",
            "result_b64":   result["result_b64"],
            "processing_s": result["processing_s"],
        }

    if state == "FAILURE":
        return JSONResponse(
            status_code=500,
            content={"task_id": task_id, "state": "FAILURE",
                     "error": str(async_result.result)}
        )

    return {"task_id": task_id, "state": state}


@app.get("/api/v1/health", tags=["System"])
async def health():
    return {"status": "ok", "version": "4.0.0", "mode": "async-celery-neural"}