"""Image clean-up tuned for phone photos of handwritten lists (blue/black pen on white paper)."""
import cv2
import numpy as np


def decode(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")
    return img


def _order_corners(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], dtype="float32")


def find_sheet(bgr: np.ndarray) -> np.ndarray:
    """Crop and perspective-correct the largest bright, unsaturated region (the paper).
    Returns the input unchanged when no plausible sheet is found."""
    h, w = bgr.shape[:2]
    scale = 1000 / max(h, w)
    small = cv2.resize(bgr, None, fx=scale, fy=scale)
    mask = cv2.inRange(cv2.cvtColor(small, cv2.COLOR_BGR2HSV), (0, 0, 150), (180, 60, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return bgr
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.15 * small.shape[0] * small.shape[1]:
        return bgr  # probably a scan / screenshot without a visible sheet edge
    approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(approx) != 4:
        approx = cv2.boxPoints(cv2.minAreaRect(c))
    pts = _order_corners(approx.reshape(-1, 2).astype("float32") / scale)
    width = int(max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[3] - pts[2])))
    height = int(max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2])))
    dst = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype="float32")
    return cv2.warpPerspective(bgr, cv2.getPerspectiveTransform(pts, dst), (width, height))


def binarize(bgr: np.ndarray) -> np.ndarray:
    """Black text on white. The red channel gives the best contrast for blue ink."""
    channel = bgr[:, :, 2]
    if max(channel.shape) < 1600:  # upscale small images; Tesseract likes ~30px tall letters
        f = 1600 / max(channel.shape)
        channel = cv2.resize(channel, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    channel = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(channel)
    bw = cv2.adaptiveThreshold(channel, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)
    return cv2.medianBlur(bw, 3)


def prepare(data: bytes) -> np.ndarray:
    return binarize(find_sheet(decode(data)))
