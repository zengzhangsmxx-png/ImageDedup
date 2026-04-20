"""AI语义相似度模块"""

from pathlib import Path
from typing import Optional, Callable
import numpy as np
from PIL import Image

from .hasher import DuplicateGroup
from ..logging_setup import get_logger

logger = get_logger(__name__)


class SemanticEngine:
    """语义相似度引擎"""

    def __init__(self, model_name: str = "ViT-B/32", device: str = "cpu"):
        """
        初始化语义引擎

        Args:
            model_name: CLIP模型名称
            device: 计算设备 (cpu/cuda)
        """
        self.model_name = model_name
        self.device = device
        self.model = None
        self.processor = None
        self._loaded = False
        logger.info(f"语义引擎初始化，模型: {model_name}, 设备: {device}")

    def _ensure_loaded(self):
        """延迟加载CLIP模型"""
        if self._loaded:
            return

        try:
            from transformers import CLIPProcessor, CLIPModel
            import torch

            logger.info(f"正在加载CLIP模型 {self.model_name}...")
            self.model = CLIPModel.from_pretrained(f"openai/{self.model_name}")
            self.processor = CLIPProcessor.from_pretrained(f"openai/{self.model_name}")

            # 移动到指定设备
            if self.device == "cuda" and torch.cuda.is_available():
                self.model = self.model.cuda()
                logger.info("模型已加载到GPU")
            else:
                self.model = self.model.cpu()
                logger.info("模型已加载到CPU")

            self.model.eval()
            self._loaded = True
            logger.info("CLIP模型加载完成")

        except ImportError as e:
            error_msg = (
                "未安装transformers库，无法使用语义相似度功能。\n"
                "请运行: pip install transformers torch"
            )
            logger.error(error_msg)
            raise ImportError(error_msg) from e
        except Exception as e:
            error_msg = f"加载CLIP模型失败: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def compute_embedding(self, image_path: str) -> np.ndarray:
        """
        计算图像嵌入向量

        Args:
            image_path: 图像文件路径

        Returns:
            归一化的嵌入向量
        """
        self._ensure_loaded()

        try:
            import torch

            # 加载图像
            image = Image.open(image_path).convert('RGB')

            # 预处理
            inputs = self.processor(images=image, return_tensors="pt")

            # 移动到设备
            if self.device == "cuda" and torch.cuda.is_available():
                inputs = {k: v.cuda() for k, v in inputs.items()}

            # 计算嵌入
            with torch.no_grad():
                image_features = self.model.get_image_features(**inputs)

            # 归一化
            embedding = image_features.cpu().numpy()[0]
            embedding = embedding / np.linalg.norm(embedding)

            return embedding

        except Exception as e:
            logger.error(f"计算图像嵌入失败 {image_path}: {e}")
            raise

    def compute_embeddings_batch(
        self,
        paths: list[str],
        batch_size: int = 32,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> dict[str, np.ndarray]:
        """
        批量计算图像嵌入

        Args:
            paths: 图像路径列表
            batch_size: 批次大小
            progress_callback: 进度回调函数 (current, total)

        Returns:
            路径到嵌入向量的映射
        """
        self._ensure_loaded()

        embeddings = {}
        total = len(paths)

        logger.info(f"开始批量计算 {total} 个图像的语义嵌入")

        for i in range(0, total, batch_size):
            batch_paths = paths[i:i + batch_size]

            for path in batch_paths:
                try:
                    embedding = self.compute_embedding(path)
                    embeddings[path] = embedding
                except Exception as e:
                    logger.warning(f"跳过图像 {path}: {e}")
                    continue

            if progress_callback:
                progress_callback(min(i + batch_size, total), total)

        logger.info(f"成功计算 {len(embeddings)}/{total} 个图像嵌入")
        return embeddings

    def find_semantic_duplicates(
        self,
        embeddings: dict[str, np.ndarray],
        threshold: float = 0.85,
        hash_map: Optional[dict] = None
    ) -> list[DuplicateGroup]:
        """
        查找语义相似的图像

        Args:
            embeddings: 路径到嵌入向量的映射
            threshold: 余弦相似度阈值 (0-1)
            hash_map: 可选的哈希映射（未使用，保留接口兼容性）

        Returns:
            重复组列表
        """
        if len(embeddings) < 2:
            return []

        paths = list(embeddings.keys())
        n = len(paths)

        logger.info(f"开始语义相似度比对，共 {n} 个图像，阈值={threshold}")

        # 构建嵌入矩阵
        embedding_matrix = np.array([embeddings[p] for p in paths])

        # 计算余弦相似度矩阵
        similarity_matrix = np.dot(embedding_matrix, embedding_matrix.T)

        # 找相似对
        similar_pairs = set()
        for i in range(n):
            for j in range(i + 1, n):
                if similarity_matrix[i, j] >= threshold:
                    similar_pairs.add((i, j))

        if not similar_pairs:
            logger.info("未发现语义相似图像")
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
            groups_dict[root].append(paths[i])

        duplicate_groups = []
        for group_paths in groups_dict.values():
            if len(group_paths) > 1:
                # 计算组内平均相似度
                group_indices = [paths.index(p) for p in group_paths]
                similarities = []
                for i in range(len(group_indices)):
                    for j in range(i + 1, len(group_indices)):
                        idx_i = group_indices[i]
                        idx_j = group_indices[j]
                        similarities.append(similarity_matrix[idx_i, idx_j])

                avg_similarity = np.mean(similarities) if similarities else 1.0

                duplicate_groups.append(DuplicateGroup(
                    files=group_paths,
                    similarity_score=float(avg_similarity),
                    match_type="语义相似"
                ))

        logger.info(f"发现 {len(duplicate_groups)} 组语义相似图像")
        return duplicate_groups
