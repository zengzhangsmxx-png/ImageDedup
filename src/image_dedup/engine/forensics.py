"""Forensic analysis — metadata, pixel diff, ELA, noise, lighting."""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image
from PIL.ExifTags import TAGS
from scipy.ndimage import gaussian_filter

from ..logging_setup import get_logger

logger = get_logger("forensics")


@dataclass
class MetadataComparison:
    file_a_meta: dict[str, str]
    file_b_meta: dict[str, str]
    differences: list[str]


@dataclass
class PixelDiffResult:
    diff_image: np.ndarray
    mean_diff: float
    max_diff: float
    diff_percentage: float


@dataclass
class ELAResult:
    ela_image_a: np.ndarray
    ela_image_b: np.ndarray
    quality_used: int


@dataclass
class NoiseAnalysis:
    noise_image_a: np.ndarray
    noise_image_b: np.ndarray
    noise_level_a: float
    noise_level_b: float


@dataclass
class LightingAnalysis:
    histogram_a: np.ndarray
    histogram_b: np.ndarray
    histogram_correlation: float
    edges_a: np.ndarray
    edges_b: np.ndarray


@dataclass
class SingleNoiseResult:
    noise_image: np.ndarray
    noise_level: float


@dataclass
class SingleLightingResult:
    histogram: np.ndarray
    edges: np.ndarray


def _extract_exif(path: str) -> dict[str, str]:
    """Extract key EXIF fields from an image."""
    meta: dict[str, str] = {}
    try:
        img = Image.open(path)
        exif = img.getexif()
        if not exif:
            return meta
        for tag_id, value in exif.items():
            tag_name = TAGS.get(tag_id, str(tag_id))
            meta[tag_name] = str(value)[:200]
    except Exception as e:
        logger.debug("EXIF extraction failed for %s: %s", path, e)
    return meta


def _load_cv2_rgb(path: str, max_dim: int = 2048) -> np.ndarray | None:
    img = cv2.imread(path)
    if img is None:
        return None
    h, w = img.shape[:2]
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return img


def _align_sizes(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Resize b to match a's dimensions."""
    ha, wa = a.shape[:2]
    hb, wb = b.shape[:2]
    if (ha, wa) != (hb, wb):
        b = cv2.resize(b, (wa, ha), interpolation=cv2.INTER_AREA)
    return a, b


class ForensicAnalyzer:

    def __init__(self, config=None):
        from ..config import AppConfig
        self._config = config or AppConfig()

    def compare_metadata(self, path_a: str, path_b: str) -> MetadataComparison:
        meta_a = _extract_exif(path_a)
        meta_b = _extract_exif(path_b)
        all_keys = sorted(set(meta_a.keys()) | set(meta_b.keys()))
        diffs = []
        for k in all_keys:
            va = meta_a.get(k, "(缺失)")
            vb = meta_b.get(k, "(缺失)")
            if va != vb:
                diffs.append(f"{k}: [{va}] vs [{vb}]")
        return MetadataComparison(meta_a, meta_b, diffs)

    def pixel_diff(self, path_a: str, path_b: str, threshold: int = 30) -> PixelDiffResult | None:
        a = _load_cv2_rgb(path_a, max_dim=self._config.forensic_max_dim)
        b = _load_cv2_rgb(path_b, max_dim=self._config.forensic_max_dim)
        if a is None or b is None:
            return None
        a, b = _align_sizes(a, b)

        diff = cv2.absdiff(a, b)
        gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

        # Create heatmap
        heatmap = cv2.applyColorMap(gray_diff, cv2.COLORMAP_JET)

        mean_val = float(np.mean(gray_diff))
        max_val = float(np.max(gray_diff))
        pct = float(np.sum(gray_diff > threshold)) / gray_diff.size * 100

        return PixelDiffResult(
            diff_image=heatmap,
            mean_diff=round(mean_val, 2),
            max_diff=round(max_val, 2),
            diff_percentage=round(pct, 2),
        )

    def error_level_analysis(self, path: str, quality: int | None = None) -> np.ndarray | None:
        """ELA: re-save at known JPEG quality, compute amplified difference."""
        if quality is None:
            quality = self._config.ela_quality
        try:
            img = Image.open(path).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            buf.seek(0)
            resaved = Image.open(buf)

            orig_arr = np.array(img, dtype=np.float32)
            resaved_arr = np.array(resaved, dtype=np.float32)

            diff = np.abs(orig_arr - resaved_arr)
            ela = np.clip(diff * self._config.ela_amplification, 0, 255).astype(np.uint8)
            return ela
        except Exception as e:
            logger.debug("ELA failed for %s: %s", path, e)
            return None

    def ela_compare(self, path_a: str, path_b: str, quality: int | None = None) -> ELAResult | None:
        if quality is None:
            quality = self._config.ela_quality
        ela_a = self.error_level_analysis(path_a, quality)
        ela_b = self.error_level_analysis(path_b, quality)
        if ela_a is None or ela_b is None:
            return None
        return ELAResult(ela_image_a=ela_a, ela_image_b=ela_b, quality_used=quality)

    def noise_analysis(self, path_a: str, path_b: str, sigma: float | None = None) -> NoiseAnalysis | None:
        """High-pass filter to reveal noise patterns."""
        if sigma is None:
            sigma = self._config.noise_sigma
        a = _load_cv2_rgb(path_a, max_dim=self._config.forensic_max_dim)
        b = _load_cv2_rgb(path_b, max_dim=self._config.forensic_max_dim)
        if a is None or b is None:
            return None

        a_gray = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
        b_gray = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)

        # High-pass = original - low-pass (Gaussian blur)
        noise_a = a_gray - gaussian_filter(a_gray, sigma=sigma)
        noise_b = b_gray - gaussian_filter(b_gray, sigma=sigma)

        # Normalize to 0-255 for display
        def normalize(arr: np.ndarray) -> np.ndarray:
            mn, mx = arr.min(), arr.max()
            if mx - mn < 1e-6:
                return np.zeros_like(arr, dtype=np.uint8)
            return ((arr - mn) / (mx - mn) * 255).astype(np.uint8)

        level_a = float(np.std(noise_a))
        level_b = float(np.std(noise_b))

        return NoiseAnalysis(
            noise_image_a=normalize(noise_a),
            noise_image_b=normalize(noise_b),
            noise_level_a=round(level_a, 2),
            noise_level_b=round(level_b, 2),
        )

    def lighting_analysis(self, path_a: str, path_b: str) -> LightingAnalysis | None:
        a = _load_cv2_rgb(path_a, max_dim=self._config.forensic_max_dim)
        b = _load_cv2_rgb(path_b, max_dim=self._config.forensic_max_dim)
        if a is None or b is None:
            return None
        a, b = _align_sizes(a, b)

        a_gray = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        b_gray = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)

        # Histograms
        hist_a = cv2.calcHist([a_gray], [0], None, [256], [0, 256]).flatten()
        hist_b = cv2.calcHist([b_gray], [0], None, [256], [0, 256]).flatten()

        # Normalize histograms
        hist_a = hist_a / (hist_a.sum() + 1e-8)
        hist_b = hist_b / (hist_b.sum() + 1e-8)

        corr = float(cv2.compareHist(
            hist_a.astype(np.float32), hist_b.astype(np.float32),
            cv2.HISTCMP_CORREL,
        ))

        # Canny edge detection
        edges_a = cv2.Canny(a_gray, self._config.canny_low, self._config.canny_high)
        edges_b = cv2.Canny(b_gray, self._config.canny_low, self._config.canny_high)

        return LightingAnalysis(
            histogram_a=hist_a, histogram_b=hist_b,
            histogram_correlation=round(corr, 4),
            edges_a=edges_a, edges_b=edges_b,
        )

    def single_noise_analysis(self, path: str, sigma: float | None = None) -> SingleNoiseResult | None:
        if sigma is None:
            sigma = self._config.noise_sigma
        img = _load_cv2_rgb(path, max_dim=self._config.forensic_max_dim)
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
        noise = gray - gaussian_filter(gray, sigma=sigma)

        mn, mx = noise.min(), noise.max()
        if mx - mn < 1e-6:
            normalized = np.zeros_like(noise, dtype=np.uint8)
        else:
            normalized = ((noise - mn) / (mx - mn) * 255).astype(np.uint8)

        return SingleNoiseResult(
            noise_image=normalized,
            noise_level=round(float(np.std(noise)), 2),
        )

    def single_lighting_analysis(self, path: str) -> SingleLightingResult | None:
        img = _load_cv2_rgb(path, max_dim=self._config.forensic_max_dim)
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [256], [0, 256]).flatten()
        hist = hist / (hist.sum() + 1e-8)
        edges = cv2.Canny(gray, self._config.canny_low, self._config.canny_high)
        return SingleLightingResult(histogram=hist, edges=edges)
