"""Hash computation — MD5/SHA256 + perceptual hashes, with multiprocessing."""

from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import imagehash
import numpy as np
from PIL import Image

from .cache import HashCache
from .scanner import ImageFile


@dataclass
class ImageHashes:
    file_path: str
    md5: str
    sha256: str
    phash: str
    dhash: str
    ahash: str
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


def _compute_single(file_path: str) -> dict | None:
    """Compute all hashes for one image. Runs in a worker process."""
    try:
        path = Path(file_path)
        data = path.read_bytes()
        md5 = hashlib.md5(data).hexdigest()
        sha256 = hashlib.sha256(data).hexdigest()

        img = Image.open(path)
        img.load()
        w, h = img.size
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        ph = str(imagehash.phash(img))
        dh = str(imagehash.dhash(img))
        ah = str(imagehash.average_hash(img))

        return dict(
            file_path=file_path, md5=md5, sha256=sha256,
            phash=ph, dhash=dh, ahash=ah,
            file_size=len(data), width=w, height=h,
            computed_at=time.time(),
        )
    except Exception:
        return None


class HashEngine:
    def __init__(self, cache: HashCache, max_workers: int | None = None):
        self._cache = cache
        self._max_workers = max_workers or min(os.cpu_count() or 4, 8)

    def compute_hashes(
        self,
        files: list[ImageFile],
        progress_callback: Callable[[int, int], None] | None = None,
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
                results.append(ImageHashes(
                    file_path=fp, md5=c["md5"], sha256=c["sha256"],
                    phash=c["phash"], dhash=c["dhash"], ahash=c["ahash"],
                    file_size=f.file_size, width=c["width"], height=c["height"],
                    computed_at=c["computed_at"],
                ))
            else:
                to_compute.append(f)
                file_map[str(f.path)] = f

        if progress_callback:
            progress_callback(len(results), total)

        if not to_compute:
            return results

        # Parallel hash computation with chunksize
        batch_for_cache: list[tuple[str, int, float, dict]] = []
        paths = [str(f.path) for f in to_compute]
        chunksize = max(1, len(paths) // (self._max_workers * 4))
        with ProcessPoolExecutor(max_workers=self._max_workers) as pool:
            for h in pool.map(_compute_single, paths, chunksize=chunksize):
                if h is not None:
                    ih = ImageHashes(**h)
                    results.append(ih)
                    f = file_map[h["file_path"]]
                    batch_for_cache.append((h["file_path"], f.file_size, mtime_map[h["file_path"]], h))
                if progress_callback:
                    progress_callback(len(results), total)

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
        used: set[int] = set()
        gid = 0

        # Build adjacency
        n = len(items)
        adj: dict[int, set[int]] = defaultdict(set)
        for i in range(n):
            for j in range(i + 1, n):
                dist = bin(items[i][0] ^ items[j][0]).count("1")
                if dist <= threshold:
                    pa, pb = items[i][1].file_path, items[j][1].file_path
                    pair = tuple(sorted([pa, pb]))
                    if pair not in exact_pairs:
                        adj[i].add(j)
                        adj[j].add(i)

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
                # Compute average similarity within group
                total_dist = 0
                count = 0
                for ci in range(len(component)):
                    for cj in range(ci + 1, len(component)):
                        total_dist += bin(items[component[ci]][0] ^ items[component[cj]][0]).count("1")
                        count += 1
                avg_dist = total_dist / count if count else 0
                similarity = max(0.0, 1.0 - avg_dist / 64.0)
                groups.append(DuplicateGroup(
                    group_id=gid, detection_method="perceptual",
                    similarity_score=round(similarity, 3),
                    files=[items[idx][1] for idx in component],
                ))

        return groups
