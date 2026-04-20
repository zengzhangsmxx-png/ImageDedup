"""Centralized configuration system — loads from settings.json with defaults."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    """Application configuration with all tunable parameters."""

    # Hasher settings
    max_workers: int = 8
    perceptual_threshold: int = 10
    blend_ratio_full: float = 0.8
    blend_ratio_top: float = 0.2
    multi_account_min_top_dist: float = 2.0
    multi_account_top_ratio: float = 1.5
    top_crop_ratio: float = 0.08

    # Feature matcher settings
    orb_n_features: int = 1000
    orb_ratio_threshold: float = 0.75
    feature_min_score: float = 0.15
    feature_max_dim: int = 1024

    # Forensics settings
    ela_quality: int = 90
    ela_amplification: float = 20.0
    noise_sigma: float = 3.0
    canny_low: int = 50
    canny_high: int = 150
    forensic_max_dim: int = 2048

    # Theme
    theme: str = "light"

    # Video dedup
    video_keyframe_interval: float = 2.0
    video_phash_threshold: int = 10

    # AI semantic
    semantic_enabled: bool = False
    semantic_model: str = "ViT-B/32"
    semantic_threshold: float = 0.85

    # Cross-document dedup
    cross_doc_enabled: bool = False

    # Batch operations
    batch_move_dir: str = ""
    auto_keep_best: bool = True
    batch_rename_pattern: str = "{prefix}_{index:03d}"

    # Performance
    gpu_acceleration: bool = False
    scan_batch_size: int = 10000
    resume_scan_enabled: bool = True

    # Scheduled scan
    scheduled_scan_enabled: bool = False
    scheduled_scan_interval_min: int = 30
    scheduled_scan_paths: list[str] = field(default_factory=list)

    # System tray
    minimize_to_tray: bool = False
    file_watcher_enabled: bool = False
    file_watcher_paths: list[str] = field(default_factory=list)

    # Format support
    heic_enabled: bool = True
    avif_enabled: bool = True

    # Extract location
    extract_to_archive_dir: bool = True

    # System settings
    log_level: str = "INFO"


def config_path() -> Path:
    config_dir = Path.home() / ".config" / "image_dedup"
    return config_dir / "settings.json"


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        valid_keys = {f.name for f in AppConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return AppConfig(**filtered)
    except Exception:
        return AppConfig()


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2, ensure_ascii=False)
