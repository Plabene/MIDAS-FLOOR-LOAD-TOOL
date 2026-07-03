from pathlib import Path

import numpy as np
from PIL import Image

try:
    import cv2
except Exception:  # pragma: no cover - depends on local install
    cv2 = None


def load_image(path):
    return np.array(Image.open(path).convert("RGB"))


def _save_debug(image, debug_dir, name):
    if not debug_dir:
        return
    Path(debug_dir).mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(Path(debug_dir) / name)


def enhance_contrast(image):
    if cv2 is None:
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if image.ndim == 3 else image
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def remove_noise(image):
    if cv2 is None:
        return image
    return cv2.fastNlMeansDenoising(image, None, 5, 7, 21)


def sharpen_image(image):
    if cv2 is None:
        return image
    kernel = np.array([[0, -0.35, 0], [-0.35, 2.4, -0.35], [0, -0.35, 0]])
    return cv2.filter2D(image, -1, kernel)


def binarize_image(image):
    if cv2 is None:
        return image
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 35, 11)


def otsu_threshold(image):
    if cv2 is None:
        return image
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def upscale_image(image, scale=2):
    if cv2 is None:
        return image
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def crop_margins(image, threshold=245):
    if cv2 is None:
        return image
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    mask = gray < threshold
    coords = np.argwhere(mask)
    if coords.size == 0:
        return image
    y1, x1 = coords.min(axis=0)
    y2, x2 = coords.max(axis=0) + 1
    pad = 20
    y1 = max(0, y1 - pad)
    x1 = max(0, x1 - pad)
    y2 = min(image.shape[0], y2 + pad)
    x2 = min(image.shape[1], x2 + pad)
    return image[y1:y2, x1:x2]


def remove_black_border(image):
    if cv2 is None:
        return image
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return crop_margins(gray, threshold=20) if np.mean(gray[:10, :]) < 80 or np.mean(gray[-10:, :]) < 80 else image


def remove_shadow_gray(image):
    if cv2 is None:
        return image
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    background = cv2.medianBlur(gray, 35)
    normalized = cv2.divide(gray, background, scale=255)
    return normalized


def remove_background_color(image):
    if cv2 is None or image.ndim != 3:
        return image
    lab = cv2.cvtColor(image, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2RGB)


def color_to_gray_optimized(image):
    if cv2 is None:
        return image
    if image.ndim == 2:
        return image
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    value = hsv[:, :, 2]
    saturation = hsv[:, :, 1]
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return cv2.addWeighted(gray, 0.75, value, 0.25, 0) - (saturation // 12)


def estimate_color_mode(image):
    if image.ndim == 2:
        unique = np.unique(image[::10, ::10])
        return "black_white" if len(unique) <= 8 else "grayscale"
    channel_std = np.mean([np.std(image[:, :, idx]) for idx in range(3)])
    channel_diff = np.mean(np.abs(image[:, :, 0].astype(float) - image[:, :, 1].astype(float)))
    if channel_diff > 3 and channel_std > 10:
        return "color"
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if cv2 is not None else image.mean(axis=2)
    unique = np.unique(gray[::10, ::10])
    return "black_white" if len(unique) <= 8 else "grayscale"


def scan_quality_metrics(image):
    gray = image if image.ndim == 2 else (cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) if cv2 is not None else image.mean(axis=2).astype("uint8"))
    contrast = float(np.std(gray))
    if cv2 is not None:
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        noise = float(np.std(lap))
    else:
        noise = 0.0
    bbox = None
    coords = np.argwhere(gray < 245)
    if coords.size:
        y1, x1 = coords.min(axis=0)
        y2, x2 = coords.max(axis=0) + 1
        bbox = [int(x1), int(y1), int(x2), int(y2)]
    return {
        "color_mode": estimate_color_mode(image),
        "scan_noise_score": round(noise, 3),
        "contrast_score": round(contrast, 3),
        "margin_bbox": bbox,
        "skew_angle": round(detect_skew_angle(gray), 3),
    }


def detect_skew_angle(image):
    if cv2 is None:
        return 0.0
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    coords = np.column_stack(np.where(gray < 250))
    if coords.size == 0:
        return 0.0
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    return float(angle if abs(angle) <= 20 else 0.0)


def deskew_image(image, angle=None):
    if cv2 is None:
        return image, 0.0
    angle = detect_skew_angle(image) if angle is None else angle
    if abs(angle) < 0.2:
        return image, 0.0
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width // 2, height // 2), angle, 1.0)
    rotated = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return rotated, angle


def detect_page_orientation(image):
    height, width = image.shape[:2]
    return 90 if width > height * 1.35 else 0


def rotate_if_needed(image, orientation=None):
    orientation = detect_page_orientation(image) if orientation is None else orientation
    if cv2 is not None and orientation == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE), orientation
    return image, 0


def enhance_table_lines(image):
    if cv2 is None:
        return image
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    horizontal = binary.copy()
    vertical = binary.copy()
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, gray.shape[1] // 40), 1))
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, gray.shape[0] // 40)))
    horizontal = cv2.dilate(cv2.erode(horizontal, h_kernel), h_kernel)
    vertical = cv2.dilate(cv2.erode(vertical, v_kernel), v_kernel)
    return cv2.add(horizontal, vertical)


def detect_table_regions(image):
    if cv2 is None:
        return []
    lines = enhance_table_lines(image)
    contours, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w * h > image.shape[0] * image.shape[1] * 0.01:
            regions.append({"x": x, "y": y, "width": w, "height": h})
    return regions


def preprocess_for_ocr(image, debug_dir=None, page_label="page"):
    working = image.copy()
    _save_debug(working, debug_dir, f"{page_label}_00_original.png")
    working, rotation = rotate_if_needed(working)
    contrast = enhance_contrast(working)
    _save_debug(contrast, debug_dir, f"{page_label}_01_contrast.png")
    sharpened = sharpen_image(contrast)
    _save_debug(sharpened, debug_dir, f"{page_label}_02_sharpened.png")
    denoised = remove_noise(sharpened)
    binary = binarize_image(denoised)
    deskewed, skew_angle = deskew_image(binary)
    _save_debug(deskewed, debug_dir, f"{page_label}_preprocessed.png")
    lines = enhance_table_lines(deskewed)
    _save_debug(lines, debug_dir, f"{page_label}_table_lines.png")
    return {
        "image": deskewed,
        "table_lines": lines,
        "page_rotation_detected": bool(rotation),
        "page_deskew_applied": abs(skew_angle) > 0,
        "skew_angle": skew_angle,
        "table_regions": detect_table_regions(deskewed),
    }


def generate_preprocess_candidates(image, debug_dir=None, page_label="page", max_candidates=12):
    working = image.copy()
    working, rotation = rotate_if_needed(working)
    cropped = crop_margins(working)
    gray = cv2.cvtColor(cropped, cv2.COLOR_RGB2GRAY) if cv2 is not None and cropped.ndim == 3 else cropped

    candidates = [
        ("candidate_01_original_gray", gray),
        ("candidate_02_contrast_clahe", enhance_contrast(cropped)),
        ("candidate_03_adaptive_threshold", binarize_image(enhance_contrast(cropped))),
        ("candidate_04_otsu_threshold", otsu_threshold(enhance_contrast(cropped))),
        ("candidate_05_sharpened", sharpen_image(enhance_contrast(cropped))),
        ("candidate_06_denoise_light", remove_noise(enhance_contrast(cropped))),
    ]

    deskewed, skew_angle = deskew_image(enhance_contrast(cropped))
    candidates.extend([
        ("candidate_07_deskew_contrast", deskewed),
        ("candidate_08_table_line_enhanced", enhance_table_lines(enhance_contrast(cropped))),
    ])

    upscaled = upscale_image(cropped, 2)
    candidates.extend([
        ("candidate_09_upscale_2x_contrast", enhance_contrast(upscaled)),
        ("candidate_10_upscale_2x_sharpen", sharpen_image(enhance_contrast(upscaled))),
        ("candidate_11_adaptive_threshold_keep_small_text", binarize_image(enhance_contrast(upscaled))),
        ("candidate_12_light_binary_no_morph", otsu_threshold(upscaled)),
        ("candidate_13_table_line_enhanced", enhance_table_lines(enhance_contrast(upscaled))),
        ("candidate_14_remove_shadow_gray", remove_shadow_gray(cropped)),
        ("candidate_15_remove_background_color", remove_background_color(cropped)),
        ("candidate_16_color_to_gray_optimized", color_to_gray_optimized(cropped)),
        ("candidate_17_high_contrast_small_text", sharpen_image(enhance_contrast(upscaled))),
        ("candidate_18_black_border_removed", remove_black_border(cropped)),
        ("candidate_19_margin_cropped", cropped),
        ("candidate_20_scan_clean_balanced", otsu_threshold(sharpen_image(remove_shadow_gray(cropped)))),
    ])

    result = []
    for index, (name, candidate_image) in enumerate(candidates[:max_candidates], start=1):
        file_name = f"{page_label}_{name}.png"
        _save_debug(candidate_image, debug_dir, file_name)
        result.append({
            "name": name,
            "image": candidate_image,
            "debug": {
                "rotation_detected": bool(rotation),
                "skew_angle": skew_angle if "deskew" in name else 0.0,
                "file_name": file_name,
            },
        })
    return result
