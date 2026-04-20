"""视频关键帧提取与哈希模块"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import cv2
import numpy as np
import imagehash
from PIL import Image

from .hasher import DuplicateGroup
from ..logging_setup import get_logger

logger = get_logger(__name__)

VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.webm'}


@dataclass
class VideoFile:
    """视频文件信息"""
    path: str
    original_path: str
    file_size: int
    duration: float
    keyframe_count: int
    source_type: str = "video"
    source_group: Optional[str] = None


@dataclass
class VideoHashes:
    """视频哈希信息"""
    file_path: str
    keyframe_hashes: list[str]  # phash hex strings
    duration: float
    frame_count: int
    width: int
    height: int


class VideoProcessor:
    """视频处理器"""

    def __init__(self, interval: float = 2.0, config=None):
        """
        初始化视频处理器

        Args:
            interval: 关键帧提取间隔（秒）
            config: 配置对象
        """
        self.interval = interval
        self.config = config
        logger.info(f"视频处理器初始化，关键帧间隔: {interval}秒")

    def extract_keyframes(self, video_path: str) -> list[np.ndarray]:
        """
        提取视频关键帧

        Args:
            video_path: 视频文件路径

        Returns:
            关键帧图像数组列表
        """
        keyframes = []
        cap = None

        try:
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error(f"无法打开视频文件: {video_path}")
                return keyframes

            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                logger.error(f"无效的视频帧率: {video_path}")
                return keyframes

            frame_interval = int(fps * self.interval)
            frame_count = 0

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_count % frame_interval == 0:
                    # 转换为RGB
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    keyframes.append(frame_rgb)

                frame_count += 1

            logger.info(f"从视频 {Path(video_path).name} 提取了 {len(keyframes)} 个关键帧")

        except Exception as e:
            logger.error(f"提取关键帧失败 {video_path}: {e}")
        finally:
            if cap is not None:
                cap.release()

        return keyframes

    def compute_video_hashes(self, video_path: str) -> Optional[VideoHashes]:
        """
        计算视频哈希

        Args:
            video_path: 视频文件路径

        Returns:
            VideoHashes对象，失败返回None
        """
        cap = None

        try:
            # 获取视频信息
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error(f"无法打开视频文件: {video_path}")
                return None

            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = total_frames / fps if fps > 0 else 0

            cap.release()
            cap = None

            # 提取关键帧
            keyframes = self.extract_keyframes(video_path)
            if not keyframes:
                logger.warning(f"未能提取关键帧: {video_path}")
                return None

            # 计算每个关键帧的phash
            keyframe_hashes = []
            for frame in keyframes:
                try:
                    pil_image = Image.fromarray(frame)
                    phash = imagehash.phash(pil_image)
                    keyframe_hashes.append(str(phash))
                except Exception as e:
                    logger.warning(f"计算关键帧哈希失败: {e}")
                    continue

            if not keyframe_hashes:
                logger.error(f"未能计算任何关键帧哈希: {video_path}")
                return None

            return VideoHashes(
                file_path=video_path,
                keyframe_hashes=keyframe_hashes,
                duration=duration,
                frame_count=len(keyframes),
                width=width,
                height=height
            )

        except Exception as e:
            logger.error(f"计算视频哈希失败 {video_path}: {e}")
            return None
        finally:
            if cap is not None:
                cap.release()

    def find_similar_videos(
        self,
        video_hashes: list[VideoHashes],
        threshold: int = 10
    ) -> list[DuplicateGroup]:
        """
        查找相似视频

        Args:
            video_hashes: 视频哈希列表
            threshold: 汉明距离阈值

        Returns:
            重复组列表
        """
        if len(video_hashes) < 2:
            return []

        logger.info(f"开始比对 {len(video_hashes)} 个视频，阈值={threshold}")

        # 构建相似图
        n = len(video_hashes)
        similar_pairs = set()

        for i in range(n):
            for j in range(i + 1, n):
                if self._videos_similar(
                    video_hashes[i],
                    video_hashes[j],
                    threshold
                ):
                    similar_pairs.add((i, j))

        if not similar_pairs:
            logger.info("未发现相似视频")
            return []

        # 使用并查集找连通分量
        parent = list(range(n))

        def find(x):
            if parent[x] != x:
                parent[x] = find(parent[x])
            return parent[x]

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i, j in similar_pairs:
            union(i, j)

        # 构建重复组
        groups_dict = {}
        for i in range(n):
            root = find(i)
            if root not in groups_dict:
                groups_dict[root] = []
            groups_dict[root].append(video_hashes[i].file_path)

        duplicate_groups = []
        for paths in groups_dict.values():
            if len(paths) > 1:
                duplicate_groups.append(DuplicateGroup(
                    files=paths,
                    similarity_score=1.0,
                    match_type="视频关键帧"
                ))

        logger.info(f"发现 {len(duplicate_groups)} 组相似视频")
        return duplicate_groups

    def _videos_similar(
        self,
        video1: VideoHashes,
        video2: VideoHashes,
        threshold: int
    ) -> bool:
        """
        判断两个视频是否相似

        两个视频相似的条件：超过50%的关键帧匹配
        """
        hashes1 = [imagehash.hex_to_hash(h) for h in video1.keyframe_hashes]
        hashes2 = [imagehash.hex_to_hash(h) for h in video2.keyframe_hashes]

        match_count = 0
        total_comparisons = 0

        # 对每个关键帧找最佳匹配
        for h1 in hashes1:
            best_distance = float('inf')
            for h2 in hashes2:
                distance = h1 - h2
                if distance < best_distance:
                    best_distance = distance

            if best_distance <= threshold:
                match_count += 1
            total_comparisons += 1

        match_ratio = match_count / total_comparisons if total_comparisons > 0 else 0
        return match_ratio > 0.5
