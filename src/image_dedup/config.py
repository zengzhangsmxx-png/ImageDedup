"""Centralized configuration system — loads from settings.json with defaults."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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

    # System settings
    log_level: str = "INFO"


def config_path() -> Path:
    """Return the path to the settings.json file."""
    config_dir = Path.home() / ".config" / "image_dedup"
    return config_dir / "settings.json"


def load_config() -> AppConfig:
    """Load configuration from settings.json, or return defaults if not found."""
    path = config_path()
    if not path.exists():
        return AppConfig()

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Filter out unknown keys for forward compatibility
        valid_keys = {f.name for f in AppConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return AppConfig(**filtered)
    except Exception:
        # If loading fails, return defaults
        return AppConfig()


def save_config(config: AppConfig) -> None:
    """Save configuration to settings.json."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(config), f, indent=2, ensure_ascii=False)
