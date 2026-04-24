"""ORB feature matching — finds partial overlaps, crops, rotations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

from ..logging_setup import get_logger
from .hasher import DuplicateGroup, ImageHashes

logger = get_logger("feature")


@dataclass
class FeatureMatch:
    file_a: str
    file_b: str
    num_keypoints_a: int
    num_keypoints_b: int
    num_good_matches: int
    similarity_score: float


class FeatureMatcher:
    def __init__(self, n_features: int = 1000, ratio_threshold: float = 0.75, max_dim: int = 1024):
        self._n_features = n_features
        self._ratio = ratio_threshold
        self._max_dim = max_dim

    def _safe_resize(self, img: np.ndarray) -> np.ndarray:
        """缩放过大的图片，防止 OpenCV 处理时内存溢出或崩溃。"""
        h, w = img.shape[:2]
        if max(h, w) > self._max_dim:
            scale = self._max_dim / max(h, w)
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        return img

    def compare_pair(self, img_a_path: str, img_b_path: str) -> FeatureMatch | None:
        try:
            # 文件预检查
            from pathlib import Path
            for p in (img_a_path, img_b_path):
                pp = Path(p)
                if not pp.is_file() or pp.stat().st_size == 0:
                    return None

            img_a = cv2.imread(img_a_path, cv2.IMREAD_GRAYSCALE)
            img_b = cv2.imread(img_b_path, cv2.IMREAD_GRAYSCALE)
            if img_a is None or img_b is None:
                return None
            if img_a.size == 0 or img_b.size == 0:
                return None

            # Resize large images for speed
            img_a = self._safe_resize(img_a)
            img_b = self._safe_resize(img_b)

            orb = cv2.ORB_create(nFeatures=self._n_features)
            kp_a, des_a = orb.detectAndCompute(img_a, None)
            kp_b, des_b = orb.detectAndCompute(img_b, None)

            if des_a is None or des_b is None or len(kp_a) < 2 or len(kp_b) < 2:
                return FeatureMatch(
                    file_a=img_a_path, file_b=img_b_path,
                    num_keypoints_a=len(kp_a) if kp_a else 0,
                    num_keypoints_b=len(kp_b) if kp_b else 0,
                    num_good_matches=0, similarity_score=0.0,
                )

            bf = cv2.BFMatcher(cv2.NORM_HAMMING)
            matches = bf.knnMatch(des_a, des_b, k=2)

            good = []
            for m_pair in matches:
                if len(m_pair) == 2:
                    m, n = m_pair
                    if m.distance < self._ratio * n.distance:
                        good.append(m)

            min_kp = min(len(kp_a), len(kp_b))
            score = len(good) / min_kp if min_kp > 0 else 0.0

            return FeatureMatch(
                file_a=img_a_path, file_b=img_b_path,
                num_keypoints_a=len(kp_a), num_keypoints_b=len(kp_b),
                num_good_matches=len(good),
                similarity_score=round(min(score, 1.0), 3),
            )
        except Exception as e:
            logger.debug("ORB compare failed %s vs %s: %s", img_a_path, img_b_path, e)
            return None

    def compare_candidates(
        self,
        candidate_hashes: list[ImageHashes],
        min_score: float = 0.15,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[DuplicateGroup]:
        pairs = []
        n = len(candidate_hashes)
        for i in range(n):
            for j in range(i + 1, n):
                pairs.append((candidate_hashes[i], candidate_hashes[j]))

        total = len(pairs)
        groups: list[DuplicateGroup] = []
        adj: dict[str, set[str]] = {}
        scores: dict[tuple[str, str], float] = {}

        for idx, (ha, hb) in enumerate(pairs):
            result = self.compare_pair(ha.file_path, hb.file_path)
            if result and result.similarity_score >= min_score:
                key = tuple(sorted([ha.file_path, hb.file_path]))
                scores[key] = result.similarity_score
                adj.setdefault(ha.file_path, set()).add(hb.file_path)
                adj.setdefault(hb.file_path, set()).add(ha.file_path)
            if progress_callback:
                progress_callback(idx + 1, total)

        # Connected components
        visited: set[str] = set()
        hash_map = {h.file_path: h for h in candidate_hashes}
        gid = 0
        for start in adj:
            if start in visited:
                continue
            component: list[str] = []
            queue = [start]
            while queue:
                node = queue.pop()
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                for nb in adj.get(node, set()):
                    if nb not in visited:
                        queue.append(nb)
            if len(component) >= 2:
                gid += 1
                # Average score within group
                total_score = 0.0
                count = 0
                for i in range(len(component)):
                    for j in range(i + 1, len(component)):
                        key = tuple(sorted([component[i], component[j]]))
                        if key in scores:
                            total_score += scores[key]
                            count += 1
                avg = total_score / count if count else 0.0
                groups.append(DuplicateGroup(
                    group_id=gid, detection_method="feature",
                    similarity_score=round(avg, 3),
                    files=[hash_map[fp] for fp in component if fp in hash_map],
                ))

        return groups
