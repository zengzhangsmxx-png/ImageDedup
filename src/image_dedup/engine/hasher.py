"""Hash computation — MD5/SHA256 + perceptual hashes, with multiprocessing."""

from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Callable

import imagehash
import numpy as np
from PIL import Image

from .cache import HashCache
from .scanner import ImageFile

# ---------------------------------------------------------------------------
# GPU detection — set once at import time
# ---------------------------------------------------------------------------
_USE_CUDA = False
try:
    import cv2
    if cv2.cuda.getCudaEnabledDeviceCount() > 0:
        _USE_CUDA = True
except Exception:
    pass


@dataclass
class ImageHashes:
    file_path: str
    md5: str
    sha256: str
    phash: str
    dhash: str
    ahash: str
    phash_top: str
    file_size: int
    width: int
    height: int
    computed_at: float


@dataclass
class DuplicateGroup:
    group_id: int
    detection_method: str  # "exact", "perceptual", "feature"
    similarity_score: float
    files: list[ImageHashes] = field(default_factory=list)
    multi_account: bool = False


def _compute_single(file_path: str, top_crop_ratio: float = 0.08) -> dict | None:
    """Compute all hashes for one image. Runs in a worker process."""
    try:
        path = Path(file_path)

        # 文件大小预检查 — 跳过过大文件避免内存溢出
        file_stat = path.stat()
        if file_stat.st_size > 500 * 1024 * 1024:  # 500MB
            return {"_error": True, "file_path": file_path, "message": "文件过大 (>500MB)，跳过"}
        if file_stat.st_size == 0:
            return {"_error": True, "file_path": file_path, "message": "空文件"}

        data = path.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        sha256 = hashlib.sha256(data).hexdigest()

        img = Image.open(path)
        img.load()
        w, h = img.size

        # 图片尺寸预检查 — 超大图片先缩放，避免 C 扩展崩溃
        MAX_PIXELS = 178_000_000  # ~13K x 13K, PIL 默认限制
        if w * h > MAX_PIXELS:
            scale = (MAX_PIXELS / (w * h)) ** 0.5
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            # 保留原始尺寸用于记录
        if w <= 0 or h <= 0:
            return {"_error": True, "file_path": file_path, "message": "无效图片尺寸"}

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        ph = str(imagehash.phash(img))
        dh = str(imagehash.dhash(img))
        ah = str(imagehash.average_hash(img))

        # Top crop hash — captures status bar differences on phone screenshots
        top_h = max(1, int(h * top_crop_ratio))
        top_crop = img.crop((0, 0, w, top_h))
        ph_top = str(imagehash.phash(top_crop))

        return dict(
            file_path=file_path, md5=md5, sha256=sha256,
            phash=ph, dhash=dh, ahash=ah, phash_top=ph_top,
            file_size=len(data), width=w, height=h,
            computed_at=time.time(),
        )
    except MemoryError:
        return {"_error": True, "file_path": file_path, "message": "内存不足"}
    except Exception as e:
        return {"_error": True, "file_path": file_path, "message": str(e)}


class HashEngine:
    def __init__(self, cache: HashCache, max_workers: int | None = None, config=None):
        from ..config import AppConfig
        self._config = config or AppConfig()
        self._cache = cache
        self._max_workers = max_workers or self._config.max_workers

    def compute_hashes(
        self,
        files: list[ImageFile],
        progress_callback: Callable[[int, int], None] | None = None,
        errors=None,
    ) -> list[ImageHashes]:
        results: list[ImageHashes] = []
        to_compute: list[ImageFile] = []
        total = len(files)

        # Batch cache lookup
        keys = []
        mtime_map: dict[str, float] = {}
        for f in files:
            fp = str(f.path)
            mt = f.path.stat().st_mtime
            keys.append((fp, f.file_size, mt))
            mtime_map[fp] = mt

        cached_map = self._cache.get_batch(keys)
        file_map: dict[str, ImageFile] = {}
        for f in files:
            fp = str(f.path)
            if fp in cached_map:
                c = cached_map[fp]
                phash_top = c.get("phash_top", "")
                if not phash_top:
                    # Legacy cache entry without phash_top — force recompute
                    to_compute.append(f)
                    file_map[fp] = f
                else:
                    results.append(ImageHashes(
                        file_path=fp, md5=c["md5"], sha256=c["sha256"],
                        phash=c["phash"], dhash=c["dhash"], ahash=c["ahash"],
                        phash_top=phash_top,
                        file_size=f.file_size, width=c["width"], height=c["height"],
                        computed_at=c["computed_at"],
                    ))
            else:
                to_compute.append(f)
                file_map[fp] = f

        if progress_callback:
            progress_callback(len(results), total)

        if not to_compute:
            return results

        # --- Batch processing ---
        # Split uncached files into chunks to bound memory usage and allow
        # incremental cache flushes on large file sets.
        batch_size = getattr(self._config, "scan_batch_size", 10000)
        compute_fn = partial(_compute_single, top_crop_ratio=self._config.top_crop_ratio)

        for batch_start in range(0, len(to_compute), batch_size):
            batch = to_compute[batch_start : batch_start + batch_size]
            paths = [str(f.path) for f in batch]
            chunksize = max(1, len(paths) // (self._max_workers * 4))

            batch_for_cache: list[tuple[str, int, float, dict]] = []
            with ProcessPoolExecutor(max_workers=self._max_workers) as pool:
                for h in pool.map(compute_fn, paths, chunksize=chunksize):
                    if h is not None and not h.get("_error"):
                        ih = ImageHashes(**h)
                        results.append(ih)
                        f = file_map[h["file_path"]]
                        batch_for_cache.append((
                            h["file_path"], f.file_size,
                            mtime_map[h["file_path"]], h,
                        ))
                    elif h is not None and h.get("_error") and errors:
                        errors.add(h["file_path"], "hash", Exception(h["message"]))
                    if progress_callback:
                        progress_callback(len(results), total)

            # Flush cache after each batch so progress is durable
            if batch_for_cache:
                self._cache.put_batch(batch_for_cache)

        return results

    def find_exact_duplicates(self, hashes: list[ImageHashes]) -> list[DuplicateGroup]:
        groups_by_md5: dict[str, list[ImageHashes]] = defaultdict(list)
        for h in hashes:
            groups_by_md5[h.md5].append(h)

        groups = []
        gid = 0
        for md5, members in groups_by_md5.items():
            if len(members) >= 2:
                gid += 1
                groups.append(DuplicateGroup(
                    group_id=gid, detection_method="exact",
                    similarity_score=1.0, files=members,
                ))
        return groups

    def find_perceptual_duplicates(
        self,
        hashes: list[ImageHashes],
        threshold: int = 10,
        hash_type: str = "phash",
        exclude_exact: bool = True,
    ) -> list[DuplicateGroup]:
        # Build exact-match set to exclude
        exact_pairs: set[tuple[str, str]] = set()
        if exclude_exact:
            by_md5: dict[str, list[str]] = defaultdict(list)
            for h in hashes:
                by_md5[h.md5].append(h.file_path)
            for paths in by_md5.values():
                if len(paths) >= 2:
                    for i in range(len(paths)):
                        for j in range(i + 1, len(paths)):
                            pair = tuple(sorted([paths[i], paths[j]]))
                            exact_pairs.add(pair)

        # Parse hashes to integers for fast comparison
        items: list[tuple[int, ImageHashes]] = []
        for h in hashes:
            hex_str = getattr(h, hash_type)
            items.append((int(hex_str, 16), h))

        # Find similar pairs using pairwise comparison
        # For 10K images this is ~50M comparisons on 64-bit ints — fast enough
        groups: list[DuplicateGroup] = []
        gid = 0

        # Build adjacency — combine full-image hash + top-region hash
        n = len(items)
        adj: dict[int, set[int]] = defaultdict(set)
        pair_dist: dict[tuple[int, int], float] = {}

        top_items: list[tuple[int, ImageHashes]] = []
        for h in hashes:
            top_hash = h.phash_top if h.phash_top else h.phash
            top_items.append((int(top_hash, 16), h))

        for i in range(n):
            for j in range(i + 1, n):
                dist_full = bin(items[i][0] ^ items[j][0]).count("1")
                if dist_full <= threshold:
                    pa, pb = items[i][1].file_path, items[j][1].file_path
                    pair = tuple(sorted([pa, pb]))
                    if pair not in exact_pairs:
                        dist_top = bin(top_items[i][0] ^ top_items[j][0]).count("1")
                        blended = dist_full * self._config.blend_ratio_full + dist_top * self._config.blend_ratio_top
                        adj[i].add(j)
                        adj[j].add(i)
                        pair_dist[(i, j)] = blended

        # Connected components via BFS
        visited: set[int] = set()
        for start in range(n):
            if start in visited or start not in adj:
                continue
            component: list[int] = []
            queue = [start]
            while queue:
                node = queue.pop()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                for nb in adj[node]:
                    if nb not in visited:
                        queue.append(nb)
            if len(component) >= 2:
                gid += 1
                total_dist = 0.0
                total_dist_full = 0.0
                total_dist_top = 0.0
                count = 0
                for ci in range(len(component)):
                    for cj in range(ci + 1, len(component)):
                        key = (min(component[ci], component[cj]), max(component[ci], component[cj]))
                        total_dist += pair_dist.get(key, 0.0)
                        # Track full-image and top-region distances separately
                        i_idx, j_idx = component[ci], component[cj]
                        dist_full = bin(items[i_idx][0] ^ items[j_idx][0]).count("1")
                        dist_top = bin(top_items[i_idx][0] ^ top_items[j_idx][0]).count("1")
                        total_dist_full += dist_full
                        total_dist_top += dist_top
                        count += 1
                avg_dist = total_dist / count if count else 0
                avg_dist_full = total_dist_full / count if count else 0
                avg_dist_top = total_dist_top / count if count else 0
                similarity = max(0.0, 1.0 - avg_dist / 64.0)

                is_multi_account = (
                    avg_dist_top >= self._config.multi_account_min_top_dist
                    and avg_dist_top > avg_dist_full * self._config.multi_account_top_ratio
                )

                groups.append(DuplicateGroup(
                    group_id=gid, detection_method="perceptual",
                    similarity_score=round(similarity, 3),
                    files=[items[idx][1] for idx in component],
                    multi_account=is_multi_account,
                ))

        return groups
