# """
# Phase 4: Updated Celery Worker – S3 + Database
# ================================================
# Extends the Phase 3 worker with:
#   1. Save the stylized image to S3 (or local storage in dev)
#   2. Write render metadata to PostgreSQL (or SQLite in dev)
#   3. Update the Render DB record on completion/failure

# Full data flow:
#   [API] → Redis queue → [This worker] → S3 (images) + DB (metadata)
# """

# import os
# import sys
# import base64
# import time
# from datetime import datetime, timezone
# from pathlib import Path

# import cv2
# import numpy as np
# from celery import Celery

# sys.path.insert(0, str(Path(__file__).parent.parent / "phase1"))
# sys.path.insert(0, str(Path(__file__).parent))

# from engine  import stylize
# from storage import storage
# from database import SessionLocal, Render, init_db

# # ─── Celery app (identical to Phase 3) ───────────────────────────
# REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# celery_app = Celery(
#     "stylized_renderer_v2",
#     broker=REDIS_URL,
#     backend=REDIS_URL,
# )
# celery_app.conf.update(
#     task_serializer="json", result_serializer="json",
#     accept_content=["json"], result_expires=3600,
#     task_track_started=True, worker_prefetch_multiplier=1, task_acks_late=True,
# )


# @celery_app.task(bind=True, name="tasks.process_and_store")
# def process_and_store_task(
#     self,
#     render_id:   str,
#     image_b64:   str,
#     k_colors:    int = 12,
#     passes:      int = 3,
#     edges:       str = "canny",
#     canny_low:   int = 50,
#     canny_high:  int = 150,
# ) -> dict:
#     """
#     Full Phase 4 task:
#       1. Decode image
#       2. Upload original to S3
#       3. Run stylize() pipeline
#       4. Upload result to S3
#       5. Update Render record in DB
#     """
#     db = SessionLocal()
#     try:
#         # ── 1. Mark as processing ─────────────────────────────────
#         render = db.query(Render).filter_by(id=render_id).first()
#         if not render:
#             render = Render(
#                 id=render_id,
#                 task_id=self.request.id,
#                 status="processing",
#                 k_colors=k_colors,
#                 edge_method=edges,
#                 bilateral_passes=passes,
#             )
#             db.add(render)
#         else:
#             render.status = "processing"
#         db.commit()

#         self.update_state(state="STARTED", meta={"progress": "Uploading original…"})

#         # ── 2. Decode image bytes ─────────────────────────────────
#         raw_bytes = base64.b64decode(image_b64)
#         _, original_url = storage.upload_image(
#             raw_bytes, folder="originals", filename_suffix="_original"
#         )

#         # ── 3. Decode into numpy for processing ───────────────────
#         nparr = np.frombuffer(raw_bytes, np.uint8)
#         image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
#         if image is None:
#             raise ValueError("Failed to decode image")

#         # ── 4. Run the pipeline ───────────────────────────────────
#         self.update_state(state="STARTED", meta={"progress": "Running stylize pipeline…"})
#         t0 = time.time()
#         result_image = stylize(
#             image, k_colors=k_colors, bilateral_passes=passes,
#             edge_method=edges, canny_low=canny_low, canny_high=canny_high
#         )
#         elapsed = round(time.time() - t0, 3)

#         # ── 5. Upload stylized result to S3 ──────────────────────
#         self.update_state(state="STARTED", meta={"progress": "Uploading result…"})
#         _, buf = cv2.imencode(".jpg", result_image, [cv2.IMWRITE_JPEG_QUALITY, 95])
#         stylized_bytes = bytes(buf)
#         _, stylized_url = storage.upload_image(
#             stylized_bytes, folder="stylized", filename_suffix="_stylized"
#         )
#         result_b64 = base64.b64encode(stylized_bytes).decode("utf-8")

#         # ── 6. Update DB record ───────────────────────────────────
#         if render:
#             render.status        = "success"
#             render.original_url  = original_url
#             render.stylized_url  = stylized_url
#             render.processing_s  = elapsed
#             render.completed_at  = datetime.now(timezone.utc)
#             db.commit()

#         return {
#             "status":       "success",
#             "render_id":    render_id,
#             "original_url": original_url,
#             "stylized_url": stylized_url,
#             "result_b64":   result_b64,
#             "processing_s": elapsed,
#         }

#     except Exception as e:
#         # ── Mark failure in DB ────────────────────────────────────
#         render = db.query(Render).filter_by(id=render_id).first()
#         if render:
#             render.status        = "failed"
#             render.error_message = str(e)
#             render.completed_at  = datetime.now(timezone.utc)
#             db.commit()
#         raise   # re-raise so Celery marks the task as FAILURE

#     finally:
#         db.close()

"""
Phase 4: Updated Celery Worker – S3 + Database
================================================
Extends the Phase 3 worker with:
  1. Save the stylized image to S3 (or local storage in dev)
  2. Write render metadata to PostgreSQL (or SQLite in dev)
  3. Update the Render DB record on completion/failure

Full data flow:
  [API] → Redis queue → [This worker] → S3 (images) + DB (metadata)
"""

import os
import sys
import base64
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from celery import Celery

sys.path.insert(0, str(Path(__file__).parent.parent / "phase1"))
sys.path.insert(0, str(Path(__file__).parent))

from engine  import stylize
from storage import storage
from database import SessionLocal, Render, init_db

# ─── Celery app (identical to Phase 3) ───────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery(
    "stylized_renderer_v2",
    broker=REDIS_URL,
    backend=REDIS_URL,
)
celery_app.conf.update(
    task_serializer="json", result_serializer="json",
    accept_content=["json"], result_expires=3600,
    task_track_started=True, worker_prefetch_multiplier=1, task_acks_late=True,
)


@celery_app.task(bind=True, name="tasks.process_and_store")
def process_and_store_task(
    self,
    render_id:   str,
    image_b64:   str,
    k_colors:    int = 12,
    passes:      int = 3,
    edges:       str = "canny",
    canny_low:   int = 50,
    canny_high:  int = 150,
    mode:        str = "auto",
    variant:     str = "H50",
) -> dict:
    """
    Full Phase 4 task:
      1. Decode image
      2. Upload original to S3
      3. Run stylize() pipeline
      4. Upload result to S3
      5. Update Render record in DB
    """
    db = SessionLocal()
    try:
        # ── 1. Mark as processing (create the row if it doesn't exist yet) ──
        render = db.query(Render).filter_by(id=render_id).first()
        if not render:
            render = Render(
                id=render_id,
                task_id=self.request.id,
                status="processing",
                k_colors=k_colors,
                edge_method=edges,
                bilateral_passes=passes,
            )
            db.add(render)
        else:
            render.status = "processing"
        db.commit()

        self.update_state(state="STARTED", meta={"progress": "Uploading original…"})

        # ── 2. Decode image bytes ─────────────────────────────────
        raw_bytes = base64.b64decode(image_b64)
        _, original_url = storage.upload_image(
            raw_bytes, folder="originals", filename_suffix="_original"
        )

        # ── 3. Decode into numpy for processing ───────────────────
        nparr = np.frombuffer(raw_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Failed to decode image")

        # ── 4. Run the pipeline ───────────────────────────────────
        self.update_state(state="STARTED", meta={"progress": "Running stylize pipeline…"})
        t0 = time.time()
        result_image = stylize(
            image, k_colors=k_colors, bilateral_passes=passes,
            edge_method=edges, canny_low=canny_low, canny_high=canny_high,
            mode=mode, variant=variant
        )
        elapsed = round(time.time() - t0, 3)

        # ── 5. Upload stylized result to S3 ──────────────────────
        self.update_state(state="STARTED", meta={"progress": "Uploading result…"})
        _, buf = cv2.imencode(".jpg", result_image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        stylized_bytes = bytes(buf)
        _, stylized_url = storage.upload_image(
            stylized_bytes, folder="stylized", filename_suffix="_stylized"
        )
        result_b64 = base64.b64encode(stylized_bytes).decode("utf-8")

        # ── 6. Update DB record ───────────────────────────────────
        if render:
            render.status        = "success"
            render.original_url  = original_url
            render.stylized_url  = stylized_url
            render.processing_s  = elapsed
            render.completed_at  = datetime.now(timezone.utc)
            db.commit()

        return {
            "status":       "success",
            "render_id":    render_id,
            "original_url": original_url,
            "stylized_url": stylized_url,
            "result_b64":   result_b64,
            "processing_s": elapsed,
        }

    except Exception as e:
        # ── Mark failure in DB ────────────────────────────────────
        render = db.query(Render).filter_by(id=render_id).first()
        if render:
            render.status        = "failed"
            render.error_message = str(e)
            render.completed_at  = datetime.now(timezone.utc)
            db.commit()
        raise   # re-raise so Celery marks the task as FAILURE

    finally:
        db.close()