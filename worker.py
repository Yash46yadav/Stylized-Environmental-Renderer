"""
Phase 3: Celery Background Worker
===================================
Why do we need this?
--------------------
The Phase 2 synchronous API has a problem: if 10 users upload images at once,
all 10 threads are blocked doing heavy OpenCV math. The server slows to a crawl
and eventually times out.

The fix: a Task Queue pattern.
  1. API server receives image → immediately returns task_id (< 5ms response)
  2. Task is put on a Redis queue
  3. Celery worker(s) pull tasks off the queue and do the real work
  4. Frontend polls /status/{task_id} until the result is ready

Key Concepts
------------
• Celery  – Python distributed task queue library
• Redis   – In-memory data store used as the "message broker" (the queue)
            and "result backend" (stores task results)
• Task    – A Python function decorated with @app.task
• Worker  – A separate process that runs Celery tasks

Architecture Diagram
--------------------
  [Client]
     │ POST /render
     ▼
  [FastAPI Server] ──push task──► [Redis Queue]
     │ return task_id                    │
     │                                   ▼
     │                          [Celery Worker]
     │                          runs stylize()
     │                          stores result in Redis
     │
     │ GET /status/{task_id}
     ▼
  [FastAPI Server] ──read──► [Redis Result Store]
     │ return image URL or PENDING
     ▼
  [Client]

Run instructions (3 terminals)
-------------------------------
  Terminal 1:  redis-server
  Terminal 2:  celery -A worker worker --loglevel=info
  Terminal 3:  uvicorn async_main:app --reload --port 8000
"""

import os
import sys
import uuid
import base64
from pathlib import Path

import cv2
import numpy as np
from celery import Celery

# Import the Phase 1 engine
sys.path.insert(0, str(Path(__file__).parent.parent / "phase1"))
from engine import stylize

# ─────────────────────────────────────────────
# CELERY APPLICATION
# ─────────────────────────────────────────────
# Redis URL: by default Redis runs locally on port 6379
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "stylized_renderer",
    broker=REDIS_URL,          # where tasks go IN
    backend=REDIS_URL,         # where results come OUT
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,           # results expire after 1 hour
    task_track_started=True,       # enables STARTED state (not just PENDING/SUCCESS)
    worker_prefetch_multiplier=1,  # don't grab more tasks than you can handle
    task_acks_late=True,           # only acknowledge task AFTER it finishes (safer)
)


# ─────────────────────────────────────────────
# BACKGROUND TASK
# ─────────────────────────────────────────────
@celery_app.task(bind=True, name="tasks.process_image")
def process_image_task(
    self,
    image_b64: str,
    k_colors: int = 12,
    passes: int = 3,
    edges: str = "canny",
    canny_low: int = 50,
    canny_high: int = 150,
) -> dict:
    """
    The background image processing task.

    Parameters
    ----------
    self      : Celery task instance (because bind=True). Lets us update task state.
    image_b64 : Base64-encoded JPEG bytes of the uploaded image.
                We can't pass file handles or numpy arrays through Redis — only
                JSON-serializable types. Base64 lets us encode binary as a string.

    Returns
    -------
    dict with:
        status       : "success"
        result_b64   : Base64-encoded JPEG of the stylized image
        processing_s : Wall-clock seconds taken
    """
    import time

    # Tell Celery this task has started (visible via AsyncResult.state)
    self.update_state(state="STARTED", meta={"progress": "Decoding image…"})

    # ── Decode base64 → numpy array ───────────────────────────────
    raw_bytes = base64.b64decode(image_b64)
    nparr     = np.frombuffer(raw_bytes, np.uint8)
    image     = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        raise ValueError("Could not decode image in worker")

    # ── Run pipeline ──────────────────────────────────────────────
    self.update_state(state="STARTED", meta={"progress": "Running stylize pipeline…"})
    t0 = time.time()

    result_image = stylize(
        image,
        k_colors=k_colors,
        bilateral_passes=passes,
        edge_method=edges,
        canny_low=canny_low,
        canny_high=canny_high,
    )

    elapsed = time.time() - t0

    # ── Encode output back to base64 for Redis storage ───────────
    self.update_state(state="STARTED", meta={"progress": "Encoding result…"})
    _, buf = cv2.imencode(".jpg", result_image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    result_b64 = base64.b64encode(bytes(buf)).decode("utf-8")

    return {
        "status":       "success",
        "result_b64":   result_b64,
        "processing_s": round(elapsed, 3),
    }
