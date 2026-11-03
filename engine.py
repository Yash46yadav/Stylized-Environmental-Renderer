"""
engine.py  —  Anime-Background Style Engine (v2)
=================================================
Drop-in replacement for the old engine.py. The stylize() signature is
unchanged, so main.py, worker.py, worker_v2.py and the frontend keep working.

What changed vs v1 (and why the old output looked bad)
------------------------------------------------------
v1  K-Means on the full-size image in BGR space  -> slow (60s) and muddy colours
v1  Warm tint added AFTER quantizing             -> everything went yellow
v1  Pure-black Canny lines on every texture      -> noisy, dirty outlines

v2  Resize to a sane working size                -> fast
v2  Grade colour FIRST (saturation + contrast)   -> vivid anime palette
v2  K-Means in LAB space on a pixel SAMPLE       -> perceptual colours, 10x faster
v2  Blend quantized colour with smoothed colour  -> painted gradients, not posterize
v2  Clean, coloured, soft lines (noise removed)  -> looks inked, not scribbled
v2  Bloom / glow pass                            -> the cinematic anime-sky look

Parameter mapping (so your existing sliders still work)
-------------------------------------------------------
k_colors          -> palette size (try 16-28 for anime backgrounds)
bilateral_passes  -> smoothing strength (more = flatter, more painted)
canny_low/high    -> line sensitivity (higher = fewer lines)
edge_method       -> 'canny' = thin clean lines, 'sobel' = softer, bolder lines
"""

import argparse
import os
import time
import threading
from pathlib import Path

import cv2
import numpy as np

MAX_DIM = 1280  # working resolution cap; keeps processing fast


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def _resize_max(image: np.ndarray, max_dim: int = MAX_DIM) -> np.ndarray:
    h, w = image.shape[:2]
    scale = max_dim / max(h, w)
    if scale >= 1.0:
        return image
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


# ─────────────────────────────────────────────
# STEP 1 - SMOOTHING (flatten texture, keep shapes)
# ─────────────────────────────────────────────
def smooth_painterly(image: np.ndarray, passes: int = 3) -> np.ndarray:
    """
    Bilateral filter passes (edge-preserving) followed by mean-shift filtering,
    which merges similar neighbouring colours into flat "paint patches".
    """
    out = image.copy()
    for _ in range(max(1, passes)):
        out = cv2.bilateralFilter(out, d=7, sigmaColor=45, sigmaSpace=7)
    out = cv2.pyrMeanShiftFiltering(out, sp=8, sr=22, maxLevel=1)
    return out


# ─────────────────────────────────────────────
# STEP 2 - COLOUR GRADE (vivid anime palette)
# ─────────────────────────────────────────────
def anime_grade(image: np.ndarray, saturation: float = 1.15, vibrance: float = 0.9,
                contrast: float = 1.08) -> np.ndarray:
    """
    Vibrance boosts PALE colours much more than already-vivid ones, which turns
    hazy washed-out skies into the deep saturated blues anime is known for,
    without making skin/foliage neon. Highlights are compressed so the sky
    never clips to white.
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
    s = hsv[:, :, 1] / 255.0
    s = s * saturation
    s = s * (1.0 + vibrance * (1.0 - np.clip(s, 0, 1)))   # vibrance
    hsv[:, :, 1] = np.clip(s * 255.0, 0, 255)
    out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    lab = cv2.cvtColor(out, cv2.COLOR_BGR2LAB).astype(np.float32)
    L = lab[:, :, 0] / 255.0
    L = 0.5 + (L - 0.5) * contrast
    L = np.clip(L, 0, 1) ** 1.08          # >1 compresses highlights, deepens mids
    lab[:, :, 0] = np.clip(L * 255.0, 0, 255)
    return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)


# ─────────────────────────────────────────────
# STEP 3 - K-MEANS IN LAB (fast, perceptual)
# ─────────────────────────────────────────────
def quantize_lab(image: np.ndarray, k: int = 20, blend: float = 0.30,
                 sample_size: int = 40000) -> np.ndarray:
    """
    1. Convert to LAB (distances match human colour perception).
    2. Fit K-Means on a random SAMPLE of pixels (huge speed-up).
    3. Assign every pixel to its nearest centroid.
    4. Median-filter to remove speckle between colour regions.
    5. Blend a little of the smooth image back so gradients survive.
    """
    h, w = image.shape[:2]
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    pixels = lab.reshape(-1, 3).astype(np.float32)

    rng = np.random.default_rng(42)
    idx = rng.choice(len(pixels), size=min(sample_size, len(pixels)), replace=False)
    sample = pixels[idx]

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 25, 0.5)
    _, _, centers = cv2.kmeans(sample, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)

    # nearest-centroid assignment in chunks (keeps memory low)
    labels = np.empty(len(pixels), dtype=np.int32)
    chunk = 200_000
    for s in range(0, len(pixels), chunk):
        block = pixels[s:s + chunk]
        d = ((block[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels[s:s + chunk] = d.argmin(axis=1)

    quant_lab = centers[labels].reshape(h, w, 3).astype(np.uint8)
    quant = cv2.cvtColor(quant_lab, cv2.COLOR_LAB2BGR)
    quant = cv2.medianBlur(quant, 5)

    return cv2.addWeighted(quant, 1.0 - blend, image, blend, 0)


# ─────────────────────────────────────────────
# STEP 4 - LINE ART (clean, soft, coloured)
# ─────────────────────────────────────────────
def line_mask(smoothed: np.ndarray, method: str = "canny",
              low: int = 50, high: int = 150, min_area: int = 40) -> np.ndarray:
    """
    Returns a soft float mask in [0, 1] (1 = line).
    Small isolated edge fragments (leaf/grass texture) are removed, which is
    the main reason v1 lines looked dirty.
    """
    gray = cv2.cvtColor(smoothed, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    if method == "sobel":
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        mag = mag / (mag.max() + 1e-6) * 255.0
        edges = (mag > max(25, low * 0.6)).astype(np.uint8) * 255
    else:
        edges = cv2.Canny(gray, low, high)

    # drop tiny fragments
    n, comp, stats, _ = cv2.connectedComponentsWithStats(edges, connectivity=8)
    keep = np.zeros_like(edges)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            keep[comp == i] = 255

    keep = cv2.dilate(keep, np.ones((2, 2), np.uint8), iterations=1)
    soft = cv2.GaussianBlur(keep.astype(np.float32) / 255.0, (0, 0), 0.9)
    return np.clip(soft * 1.4, 0, 1)


def apply_lines(color: np.ndarray, mask: np.ndarray, strength: float = 0.55) -> np.ndarray:
    """
    Lines are a DARKER VERSION of the local colour (not pure black) - this is
    how anime backgrounds are inked, and it avoids the harsh 'sticker' look.
    """
    dark = (color.astype(np.float32) * 0.30)
    m = (mask * strength)[:, :, None]
    out = color.astype(np.float32) * (1 - m) + dark * m
    return np.clip(out, 0, 255).astype(np.uint8)


# ─────────────────────────────────────────────
# STEP 5 - BLOOM / GLOW (cinematic anime sky)
# ─────────────────────────────────────────────
def bloom(image: np.ndarray, threshold: float = 0.80, strength: float = 0.18) -> np.ndarray:
    """Blur the bright areas and screen-blend them back on top."""
    f = image.astype(np.float32) / 255.0
    lum = f.mean(axis=2, keepdims=True)
    bright = f * np.clip((lum - threshold) / (1 - threshold), 0, 1)
    glow = cv2.GaussianBlur(bright, (0, 0), sigmaX=max(image.shape[:2]) / 55)
    out = 1 - (1 - f) * (1 - glow * strength)       # screen blend
    return np.clip(out * 255.0, 0, 255).astype(np.uint8)


# ─────────────────────────────────────────────
# NEURAL MODE  (AnimeGANv3 via ONNX Runtime)
# ─────────────────────────────────────────────
# Put the model file here:  <folder of engine.py>/models/animeganv3_H50_model.onnx
# Variants: H40 (clean/bright), H50 (balanced), H64 (darker, heavier ink)
MODEL_DIR = Path(__file__).resolve().parent / "models"
_sessions = {}
_lock = threading.Lock()


def model_path(variant: str = "H50") -> Path:
    return MODEL_DIR / f"animeganv3_{variant}_model.onnx"


def neural_available(variant: str = "H50") -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return model_path(variant).exists()


def _get_session(variant: str):
    """Load the ONNX model once and reuse it (loading takes ~1s)."""
    with _lock:
        if variant not in _sessions:
            import onnxruntime as ort
            _sessions[variant] = ort.InferenceSession(
                str(model_path(variant)), providers=["CPUExecutionProvider"])
        return _sessions[variant]


def neural_anime(image: np.ndarray, variant: str = "H50", max_dim: int = 1024) -> np.ndarray:
    """
    Run the AnimeGANv3 generator. The network needs width/height divisible by
    32, input scaled to [-1, 1] in RGB, and returns [-1, 1] RGB.
    """
    h, w = image.shape[:2]
    scale = min(1.0, max_dim / max(h, w))
    nw = max(256, int(w * scale) // 32 * 32)
    nh = max(256, int(h * scale) // 32 * 32)
    small = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_AREA)

    x = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1.0
    sess = _get_session(variant)
    y = sess.run(None, {sess.get_inputs()[0].name: x[None]})[0]
    y = ((y.squeeze() + 1.0) / 2.0 * 255.0).clip(0, 255).astype(np.uint8)
    return cv2.cvtColor(y, cv2.COLOR_RGB2BGR)


def anime_finish(image: np.ndarray) -> np.ndarray:
    """Cinematic finishing on top of the neural result: richer colour + glow."""
    graded = anime_grade(image, saturation=1.10, vibrance=0.6, contrast=1.05)
    return bloom(graded, threshold=0.78, strength=0.22)


# ─────────────────────────────────────────────
# NEURAL MODE — FACE / PORTRAIT  (face_paint_512_v2 via ONNX)
# ─────────────────────────────────────────────
# Put the model file here: <folder of engine.py>/models/face_paint_512_v2_0.onnx
# This model is trained on anime PORTRAITS, not scenery — use it for photos
# of people. Use the landscape model (H40/H50/H64) for backgrounds/nature.
_face_cascade = None


def face_model_path() -> Path:
    return MODEL_DIR / "face_paint_512_v2_0.onnx"


def face_model_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return face_model_path().exists()


def _get_face_session():
    with _lock:
        if "face_paint" not in _sessions:
            import onnxruntime as ort
            _sessions["face_paint"] = ort.InferenceSession(
                str(face_model_path()), providers=["CPUExecutionProvider"])
        return _sessions["face_paint"]


def detect_face_ratio(image: np.ndarray) -> float:
    """
    Returns the fraction of image area covered by detected faces.
    Used by mode='auto' to pick the face model over the landscape model.
    Uses OpenCV's built-in Haar cascade - no extra download needed.
    """
    global _face_cascade
    if _face_cascade is None:
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(path)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = _face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                           minSize=(60, 60))
    if len(faces) == 0:
        return 0.0
    area = sum(w * h for (x, y, w, h) in faces)
    return area / (image.shape[0] * image.shape[1])


def neural_face(image: np.ndarray, size: int = 512) -> np.ndarray:
    """Anime-fy a portrait. Input normalized to [-1,1], NCHW layout."""
    small = cv2.resize(image, (size, size))
    x = cv2.cvtColor(small, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 * 2 - 1
    x = x.transpose(2, 0, 1)[None]

    sess = _get_face_session()
    y = sess.run(None, {sess.get_inputs()[0].name: x})[0].squeeze(0)
    y = (y * 0.5 + 0.5).clip(0, 1) * 255.0
    y = y.transpose(1, 2, 0).astype(np.uint8)
    y = cv2.cvtColor(y, cv2.COLOR_RGB2BGR)
    return cv2.resize(y, (image.shape[1], image.shape[0]))


# ─────────────────────────────────────────────
# CLASSIC MODE (pure OpenCV, no model needed)
# ─────────────────────────────────────────────
def stylize_classic(image, k_colors=12, bilateral_passes=3,
                    edge_method="canny", canny_low=50, canny_high=150):
    print("  [1/5] Resize + painterly smoothing ...")
    work = _resize_max(image)
    smooth = smooth_painterly(work, passes=bilateral_passes)
    print("  [2/5] Anime colour grade ...")
    graded = anime_grade(smooth)
    print("  [3/5] LAB K-Means palette ...")
    painted = quantize_lab(graded, k=int(np.clip(k_colors + 6, 6, 40)))
    print("  [4/5] Line art ...")
    inked = apply_lines(painted, line_mask(smooth, edge_method, canny_low, canny_high))
    print("  [5/5] Bloom ...")
    return bloom(inked)


# ─────────────────────────────────────────────
# FULL PIPELINE  (signature unchanged -> worker / API need no edits)
# ─────────────────────────────────────────────
def stylize(image: np.ndarray,
            k_colors: int = 12,
            bilateral_passes: int = 3,
            edge_method: str = "canny",
            canny_low: int = 50,
            canny_high: int = 150,
            mode: str = "auto",
            variant: str = "H50") -> np.ndarray:
    """
    mode = 'auto'      -> detects faces; routes to face model, else landscape
                           model, else classic OpenCV (whichever is available)
    mode = 'face'      -> anime portrait model (face_paint_512_v2) only
    mode = 'neural'    -> anime landscape model (AnimeGANv3) only
    mode = 'classic'   -> OpenCV only (uses k_colors / passes / edge sliders)

    NOTE: in 'face' and 'neural' modes the K-Means / bilateral / Canny
    sliders have NO effect - the network ignores them by design.
    """
    if mode == "auto":
        if face_model_available() and detect_face_ratio(image) > 0.08:
            mode = "face"
        elif neural_available(variant):
            mode = "neural"
        else:
            mode = "classic"

    if mode == "face":
        if not face_model_available():
            raise FileNotFoundError(
                f"Model not found: {face_model_path()}. "
                "Download face_paint_512_v2_0.onnx into the models/ folder.")
        print("  [neural-face] face_paint_512_v2 ...")
        out = neural_face(image)
        print("  [finish] colour + glow ...")
        return anime_finish(out)

    if mode == "neural":
        if not neural_available(variant):
            raise FileNotFoundError(
                f"Model not found: {model_path(variant)}. "
                "Download animeganv3_%s_model.onnx into the models/ folder." % variant)
        print(f"  [neural] AnimeGANv3-{variant} ...")
        out = neural_anime(image, variant)
        print("  [finish] colour + glow ...")
        return anime_finish(out)

    print("  [classic] OpenCV pipeline ...")
    return stylize_classic(image, k_colors, bilateral_passes,
                           edge_method, canny_low, canny_high)


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Anime-style renderer")
    p.add_argument("--input", "-i", required=True)
    p.add_argument("--output", "-o", default="output_stylized.jpg")
    p.add_argument("--colors", "-k", type=int, default=12)
    p.add_argument("--passes", "-p", type=int, default=3)
    p.add_argument("--edges", "-e", default="canny")
    p.add_argument("--low", type=int, default=50)
    p.add_argument("--high", type=int, default=150)
    p.add_argument("--mode", default="auto", choices=["auto", "face", "neural", "classic"])
    p.add_argument("--variant", default="H50", choices=["H40", "H50", "H64"])
    a = p.parse_args()

    if not os.path.exists(a.input):
        print(f"ERROR: '{a.input}' not found")
        return
    img = cv2.imread(a.input)
    if img is None:
        print("ERROR: could not read image")
        return

    t0 = time.time()
    out = stylize(img, a.colors, a.passes, a.edges, a.low, a.high, a.mode, a.variant)
    cv2.imwrite(a.output, out, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"Done in {time.time() - t0:.2f}s -> {a.output}")


if __name__ == "__main__":
    main()