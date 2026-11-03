# Stylized Environmental Renderer

Turns ordinary photos into anime / painterly art. Upload a photo, get a task ID
instantly, and a background worker does the heavy image processing.

## Features
- **Three render modes:** anime landscape model (AnimeGANv3), anime portrait model
  (face-paint v2), and a classic OpenCV pipeline (bilateral filter, LAB K-Means, Canny edges)
- **Async architecture:** FastAPI returns a task ID immediately; Celery workers
  process images in the background via Redis
- **Job tracking:** every render (status, parameters, timing, file URLs) is stored
  in PostgreSQL through SQLAlchemy
- **Storage layer:** local disk by default, with AWS S3 (boto3) support written but
  only tested locally
- **Frontend:** single-page drag-and-drop UI in vanilla JavaScript with status polling

## Architecture
```
Browser -> FastAPI -> Redis queue -> Celery worker -> engine.py (OpenCV / ONNX)
                                          |-> storage.py  (disk / S3)
                                          |-> database.py (PostgreSQL)
Browser polls GET /api/v1/status/{task_id} every 2s until the result is ready.
```

## Setup
Requires Python 3.11+, Redis, and PostgreSQL.

```bash
python -m venv venv
venv\Scripts\activate          # Windows  (source venv/bin/activate on Mac/Linux)
pip install -r requirements.txt
```

1. Create a PostgreSQL database named `stylized_renderer`.
2. Copy `.env.example` to `.env` and put in your real password.
3. Download the models into a `models/` folder next to `engine.py`:
   - `animeganv3_H50_model.onnx` (landscapes) from `zunan-islands/AnimeGANv3-Python` -> `models/`
   - `face_paint_512_v2_0.onnx` (portraits) from `hpc203/AnimeGAN-onnxruntime`

   Without the models the app still runs in Classic (OpenCV) mode.

> **Licence note:** the AnimeGANv3 weights are for non-commercial use only.
> This project is for learning and portfolio purposes.

## Run (3 terminals, venv active in each)
```bash
redis-server
celery -A worker_v2 worker --loglevel=info --concurrency=2 -P threads
uvicorn async_main:app --reload --port 8000
```
Then open `frontend.html` in a browser. API docs are at http://localhost:8000/docs.

## Project layout
| File | Purpose |
|------|---------|
| `engine.py` | Image pipeline: classic OpenCV + neural ONNX modes |
| `async_main.py` | FastAPI app: `/render`, `/status/{task_id}` |
| `worker_v2.py` | Celery task: process, store, record in DB |
| `database.py` | SQLAlchemy `Render` model |
| `storage.py` | Local disk / S3 storage service |
| `main.py`, `worker.py` | Earlier synchronous API and simple worker (kept for reference) |
| `frontend.html` | Single-page UI |

## Limitations / next steps
- Auto face detection is unreliable on occluded faces, so pick the mode manually
- Images are passed through Redis as base64; passing storage keys would be leaner
- No authentication yet (`user_id` is unused)