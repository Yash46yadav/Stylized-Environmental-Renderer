# """
# Phase 1: Core Algorithmic Engine
# =================================
# The heart of the stylized renderer. This module implements the full
# image-processing pipeline:
#   1. Bilateral Filter   → smooth colors, keep hard edges
#   2. K-Means Clustering → quantize palette (cartoon look)
#   3. Edge Detection     → black ink outlines
#   4. Composite          → merge layers into final painterly image
#
# Run directly:
#     python engine.py --input photo.jpg --output result.jpg
# """
#
# import cv2
# import numpy as np
# import argparse
# import os
# import time
#
#
# # ─────────────────────────────────────────────
# # STEP 1 – BILATERAL FILTER
# # ─────────────────────────────────────────────
# def apply_bilateral_filter(image: np.ndarray,
#                             diameter: int = 9,
#                             sigma_color: float = 75,
#                             sigma_space: float = 75,
#                             passes: int = 3) -> np.ndarray:
#     """
#     Smooth colors while preserving edges (unlike Gaussian blur which blurs everything).
#
#     Parameters
#     ----------
#     diameter     : Pixel neighbourhood diameter. Larger = slower but smoother.
#     sigma_color  : Range of colors to mix. High = mixes dissimilar colors too.
#     sigma_space  : Spatial reach. High = farther pixels influence each other.
#     passes       : Run the filter multiple times for a stronger painterly effect.
#
#     How it works
#     ------------
#     A bilateral filter is like Gaussian blur but with a second "range" kernel.
#     It only blends pixels that are both *close in space* AND *close in color*.
#     Result: flat areas go silky smooth but edges stay crisp.
#     """
#     result = image.copy()
#     for _ in range(passes):
#         result = cv2.bilateralFilter(result, diameter, sigma_color, sigma_space)
#     return result
#
#
# # ─────────────────────────────────────────────
# # STEP 2 – K-MEANS COLOR QUANTIZATION
# # ─────────────────────────────────────────────
# def apply_kmeans_quantization(image: np.ndarray,
#                                k: int = 12,
#                                iterations: int = 20,
#                                epsilon: float = 1.0) -> np.ndarray:
#     """
#     Reduce the image to exactly K colors — the classic "flat-color" cartoon look.
#
#     Parameters
#     ----------
#     k          : Number of colors in the final palette. 8–16 looks cartoonish,
#                  32+ starts to look photographic again.
#     iterations : Max K-Means iterations per attempt.
#     epsilon    : Convergence threshold; stop early if centroids move less than this.
#
#     How it works
#     ------------
#     K-Means groups all pixel colors into K clusters. Every pixel is then
#     replaced with its cluster's *mean color*. Think of it as collapsing
#     millions of shades into a hand-picked palette.
#
#     Algorithm
#     ---------
#     1. Flatten image → list of (R, G, B) points.
#     2. Randomly pick K starting centroids.
#     3. Assign each pixel to its nearest centroid (Euclidean distance in RGB).
#     4. Recompute centroids as the mean of their assigned pixels.
#     5. Repeat 3-4 until convergence.
#     6. Repaint every pixel with its centroid color.
#     """
#     # Reshape to a 2D array of pixels: shape (H*W, 3)
#     h, w = image.shape[:2]
#     pixel_data = image.reshape((-1, 3)).astype(np.float32)
#
#     # K-Means termination criteria
#     criteria = (
#         cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
#         iterations,
#         epsilon
#     )
#
#     # Run K-Means (cv2.KMEANS_PP_CENTERS = smart initialisation, faster convergence)
#     _, labels, centers = cv2.kmeans(
#         pixel_data,
#         k,
#         None,
#         criteria,
#         attempts=5,
#         flags=cv2.KMEANS_PP_CENTERS
#     )
#
#     # Map each pixel label back to its centroid color
#     centers = np.uint8(centers)
#     quantized = centers[labels.flatten()]
#     return quantized.reshape((h, w, 3))
#
#
# # ─────────────────────────────────────────────
# # STEP 3 – EDGE DETECTION
# # ─────────────────────────────────────────────
# def apply_edge_detection(image: np.ndarray,
#                           method: str = "canny",
#                           low_threshold: int = 50,
#                           high_threshold: int = 150,
#                           blur_ksize: int = 5,
#                           edge_thickness: int = 1) -> np.ndarray:
#     """
#     Generate black ink outlines from the image.
#
#     Parameters
#     ----------
#     method          : 'canny' (cleaner) or 'sobel' (more artistic/rough).
#     low_threshold   : Canny: weak edge minimum gradient.
#     high_threshold  : Canny: strong edge minimum gradient.
#     blur_ksize      : Gaussian blur kernel before edge detection (noise reduction).
#     edge_thickness  : Dilate the edge mask to thicken lines.
#
#     Returns
#     -------
#     A single-channel (grayscale) edge mask: 255 = edge, 0 = flat area.
#     """
#     gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
#     blurred = cv2.GaussianBlur(gray, (blur_ksize, blur_ksize), 0)
#
#     if method == "sobel":
#         # Sobel computes the gradient magnitude in X and Y independently
#         sobelx = cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3)
#         sobely = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)
#         magnitude = np.sqrt(sobelx**2 + sobely**2)
#         magnitude = np.uint8(np.clip(magnitude / magnitude.max() * 255, 0, 255))
#         _, edges = cv2.threshold(magnitude, 40, 255, cv2.THRESH_BINARY)
#     else:
#         # Canny: non-maximum suppression + hysteresis thresholding → cleaner lines
#         edges = cv2.Canny(blurred, low_threshold, high_threshold)
#
#     # Optionally thicken the lines
#     if edge_thickness > 1:
#         kernel = np.ones((edge_thickness, edge_thickness), np.uint8)
#         edges = cv2.dilate(edges, kernel, iterations=1)
#
#     return edges
#
#
# # ─────────────────────────────────────────────
# # STEP 4 – COLOR GRADING
# # ─────────────────────────────────────────────
# def apply_color_grade(image: np.ndarray,
#                        saturation_boost: float = 1.4,
#                        contrast_alpha: float = 1.1,
#                        contrast_beta: int = 10,
#                        warm_tint: tuple = (0, 5, 15)) -> np.ndarray:
#     """
#     Push the image toward a warm, cinematic, hand-painted look.
#
#     Parameters
#     ----------
#     saturation_boost : 1.0 = unchanged, >1 = more vivid.
#     contrast_alpha   : Multiply brightness (1.0 = unchanged).
#     contrast_beta    : Add to every channel (0 = unchanged).
#     warm_tint        : (B, G, R) to add for a sunset/warm-film feel.
#     """
#     # Saturation in HSV space
#     hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV).astype(np.float32)
#     hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation_boost, 0, 255)
#     result = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
#
#     # Contrast + brightness
#     result = cv2.convertScaleAbs(result, alpha=contrast_alpha, beta=contrast_beta)
#
#     # Warm tint: add a small constant to R channel, subtract from B
#     b, g, r = cv2.split(result.astype(np.int16))
#     b = np.clip(b + warm_tint[0], 0, 255).astype(np.uint8)
#     g = np.clip(g + warm_tint[1], 0, 255).astype(np.uint8)
#     r = np.clip(r + warm_tint[2], 0, 255).astype(np.uint8)
#
#     return cv2.merge([b, g, r])
#
#
# # ─────────────────────────────────────────────
# # STEP 5 – COMPOSITE (merge all layers)
# # ─────────────────────────────────────────────
# def composite(color_layer: np.ndarray,
#                edge_mask: np.ndarray,
#                edge_color: tuple = (20, 20, 20)) -> np.ndarray:
#     """
#     Overlay black ink outlines on the color-quantized, graded image.
#
#     Strategy
#     --------
#     - Where edge_mask == 255 → paint edge_color (dark ink)
#     - Where edge_mask == 0   → keep original color pixel
#
#     Parameters
#     ----------
#     color_layer : The processed color image (bilateral → kmeans → grade).
#     edge_mask   : Grayscale edge map (0 or 255).
#     edge_color  : BGR color for the ink lines.
#     """
#     result = color_layer.copy()
#
#     # Build a boolean mask and paint edges
#     is_edge = edge_mask == 255
#     result[is_edge] = edge_color
#
#     return result
#
#
# # ─────────────────────────────────────────────
# # FULL PIPELINE
# # ─────────────────────────────────────────────
# def stylize(image: np.ndarray,
#             k_colors: int = 12,
#             bilateral_passes: int = 3,
#             edge_method: str = "canny",
#             canny_low: int = 50,
#             canny_high: int = 150) -> np.ndarray:
#     """
#     Master pipeline function — takes a raw BGR image, returns a stylized one.
#
#     Pipeline order matters:
#       Raw → Bilateral (smooth) → K-Means (palette) → Grade (cinematic) → Edges → Composite
#     """
#     print("  [1/5] Bilateral filter …")
#     smoothed = apply_bilateral_filter(image, passes=bilateral_passes)
#
#     print("  [2/5] K-Means quantization …")
#     quantized = apply_kmeans_quantization(smoothed, k=k_colors)
#
#     print("  [3/5] Color grading …")
#     graded = apply_color_grade(quantized)
#
#     print("  [4/5] Edge detection …")
#     edges = apply_edge_detection(
#         image,                  # run on original for crisper lines
#         method=edge_method,
#         low_threshold=canny_low,
#         high_threshold=canny_high
#     )
#
#     print("  [5/5] Compositing …")
#     final = composite(graded, edges)
#
#     return final
#
#
# # ─────────────────────────────────────────────
# # CLI ENTRY POINT
# # ─────────────────────────────────────────────
# def main():
#     parser = argparse.ArgumentParser(
#         description="Stylized Environmental Renderer – Phase 1 Engine"
#     )
#     parser.add_argument("--input",   "-i", required=True,  help="Path to input .jpg/.png")
#     parser.add_argument("--output",  "-o", default="output_stylized.jpg", help="Output path")
#     parser.add_argument("--colors",  "-k", type=int,   default=12,     help="K-Means palette size")
#     parser.add_argument("--passes",  "-p", type=int,   default=3,      help="Bilateral filter passes")
#     parser.add_argument("--edges",   "-e", default="canny",            help="Edge method: canny | sobel")
#     parser.add_argument("--low",           type=int,   default=50,     help="Canny low threshold")
#     parser.add_argument("--high",          type=int,   default=150,    help="Canny high threshold")
#     args = parser.parse_args()
#
#     if not os.path.exists(args.input):
#         print(f"ERROR: Input file '{args.input}' not found.")
#         return
#
#     print(f"\n🎨 Stylized Renderer – Phase 1")
#     print(f"   Input  : {args.input}")
#     print(f"   Colors : {args.colors} (K-Means)")
#     print(f"   Edges  : {args.edges}")
#     print()
#
#     image = cv2.imread(args.input)
#     if image is None:
#         print("ERROR: Could not read image (check format/path).")
#         return
#
#     t0 = time.time()
#     result = stylize(
#         image,
#         k_colors=args.colors,
#         bilateral_passes=args.passes,
#         edge_method=args.edges,
#         canny_low=args.low,
#         canny_high=args.high
#     )
#     elapsed = time.time() - t0
#
#     cv2.imwrite(args.output, result)
#     print(f"\n✅  Done in {elapsed:.2f}s  →  {args.output}")
#
#
# if __name__ == "__main__":
#     main()

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
    mode = 'auto'    -> neural if the model file exists, otherwise classic
    mode = 'neural'  -> neural only (raises if model missing)
    mode = 'classic' -> OpenCV only (uses k_colors / passes / edge sliders)

    NOTE: in neural mode the K-Means / bilateral / Canny sliders have no effect.
    """
    use_neural = (mode == "neural") or (mode == "auto" and neural_available(variant))
    if use_neural:
        if not neural_available(variant):
            raise FileNotFoundError(
                f"Model not found: {model_path(variant)}. "
                "Download animeganv3_%s_model.onnx into the models/ folder." % variant)
        print(f"  [neural] AnimeGANv3-{variant} ...")
        out = neural_anime(image, variant)
        print("  [finish] colour + glow ...")
        return anime_finish(out)

    print("  (model not found - using classic OpenCV mode)")
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
    p.add_argument("--mode", default="auto", choices=["auto", "neural", "classic"])
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