# -*- coding: utf-8 -*-
"""
本地 Embedding 封装模块

使用 sentence-transformers 的 all-MiniLM-L6-v2 模型生成文本向量。
优先使用 ONNX Runtime 推理（轻量），回退到 PyTorch。
支持批量编码、缓存、以及无模型时的 fallback（TF-IDF 风格哈希向量）。

向量维度: 384 (all-MiniLM-L6-v2)
"""

import os
import re
import hashlib
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple, Union

# ============================================================
# 常量
# ============================================================

# 默认模型名（HuggingFace hub）
DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# 向量维度
EMBEDDING_DIM = 384
# 模型缓存目录
_MODEL_CACHE_DIR = Path(__file__).parent.parent.parent / "cache" / "memory" / "embeddings"

# ============================================================
# 全局单例
# ============================================================
_embedder_instance = None


class LocalEmbedder:
    """本地文本 Embedding 编码器

    加载优先级:
    1. sentence-transformers (最优质量)
    2. 纯 fallback: 基于字符 n-gram 的伪向量 (零依赖，质量有限但可用)
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, cache_dir: Optional[Path] = None):
        self.model_name = model_name
        self.cache_dir = cache_dir or _MODEL_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.dim = EMBEDDING_DIM
        self._model = None
        self._backend = "none"  # "sentence-transformers" | "fallback"
        self._encode_cache = {}  # 小型内存缓存: hash -> vector
        self._max_cache = 2000

        self._try_load_model()

    # ==========================================================
    # 模型加载
    # ==========================================================

    def _try_load_model(self):
        """尝试加载 sentence-transformers 模型"""
        # 1. sentence-transformers
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                self.model_name,
                cache_folder=str(self.cache_dir),
            )
            self._backend = "sentence-transformers"
            self.dim = self._model.get_sentence_embedding_dimension()
            print(f"[Embedding] 加载成功: {self.model_name} (dim={self.dim}, backend=sentence-transformers)")
            return
        except ImportError:
            print("[Embedding] sentence-transformers 未安装")
        except Exception as e:
            print(f"[Embedding] sentence-transformers 加载失败: {e}")

        # 2. Fallback: 双语词法 + 领域别名伪向量
        self._backend = "fallback"
        self.dim = EMBEDDING_DIM
        print(f"[Embedding] 使用 fallback 模式 (bilingual lexical, dim={self.dim})")

    @property
    def is_semantic(self) -> bool:
        """是否使用真正的语义模型（非 fallback）"""
        return self._backend == "sentence-transformers"

    # ==========================================================
    # 编码接口
    # ==========================================================

    def encode(self, text: str) -> np.ndarray:
        """将单条文本编码为向量

        Args:
            text: 输入文本

        Returns:
            归一化后的 float32 向量, shape=(dim,)
        """
        if not text or not text.strip():
            return np.zeros(self.dim, dtype=np.float32)

        # 内存缓存
        cache_key = hashlib.md5(text.encode('utf-8', errors='ignore')).hexdigest()
        if cache_key in self._encode_cache:
            return self._encode_cache[cache_key]

        if self._backend == "sentence-transformers":
            vec = self._encode_st(text)
        else:
            vec = self._encode_fallback(text)

        # 归一化
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        vec = vec.astype(np.float32)

        # 写入缓存（LRU 风格限制大小）
        if len(self._encode_cache) >= self._max_cache:
            # 删除最早的 20%
            keys = list(self._encode_cache.keys())
            for k in keys[:len(keys) // 5]:
                del self._encode_cache[k]
        self._encode_cache[cache_key] = vec

        return vec

    def encode_batch(self, texts: List[str]) -> np.ndarray:
        """批量编码

        Args:
            texts: 文本列表

        Returns:
            shape=(len(texts), dim) 的归一化向量矩阵
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)

        if self._backend == "sentence-transformers":
            return self._encode_batch_st(texts)

        # Fallback: 逐条编码
        vecs = [self.encode(t) for t in texts]
        return np.array(vecs, dtype=np.float32)

    # ==========================================================
    # sentence-transformers 编码
    # ==========================================================

    def _encode_st(self, text: str) -> np.ndarray:
        """使用 sentence-transformers 编码单条文本"""
        vec = self._model.encode(text, show_progress_bar=False, normalize_embeddings=True)
        return np.array(vec, dtype=np.float32)

    def _encode_batch_st(self, texts: List[str]) -> np.ndarray:
        """使用 sentence-transformers 批量编码"""
        vecs = self._model.encode(texts, show_progress_bar=False,
                                  normalize_embeddings=True, batch_size=32)
        return np.array(vecs, dtype=np.float32)

    # ==========================================================
    # Fallback: 双语词法向量
    # ==========================================================

    # CJK Unicode 区段（涵盖常用汉字、日文、韩文）
    _CJK_RE = re.compile(
        r'[\u4e00-\u9fff'      # CJK 统一表意文字
        r'\u3400-\u4dbf'       # CJK 扩展 A
        r'\uf900-\ufaff'       # CJK 兼容表意文字
        r'\u3040-\u309f'       # 平假名
        r'\u30a0-\u30ff'       # 片假名
        r'\uac00-\ud7af]+'     # 韩文音节
    )
    _EN_WORD_RE = re.compile(r'[a-z0-9][a-z0-9_\-]*')

    _BILINGUAL_ALIASES = {
        "节点": ("node", "nodes"),
        "网络": ("network", "networks", "graph"),
        "场景": ("scene", "stage"),
        "路径": ("path", "paths"),
        "层级": ("hierarchy", "tree"),
        "上下文": ("context", "contexts"),
        "子网": ("subnet", "subnetwork"),
        "数字资产": ("hda", "asset", "assets", "digital_asset"),
        "资产": ("asset", "assets", "hda"),
        "参数": ("parameter", "parameters", "parm", "parms"),
        "通道": ("channel", "channels", "chop"),
        "关键帧": ("keyframe", "keyframes", "key"),
        "属性": ("attribute", "attributes", "attrib", "attribs"),
        "组": ("group", "groups"),
        "点组": ("point_group", "pointgroup", "point groups"),
        "面组": ("primitive_group", "primgroup", "primitive groups"),
        "法线": ("normal", "normals", "n"),
        "切线": ("tangent", "tangents"),
        "颜色": ("color", "colour", "cd"),
        "位置": ("position", "pos", "p"),
        "顶点": ("vertex", "vertices"),
        "点云": ("pointcloud", "point_cloud", "points"),
        "材质": ("material", "materials", "shader", "shaders"),
        "贴图": ("texture", "textures", "map", "maps"),
        "着色器": ("shader", "shaders", "material"),
        "灯光": ("light", "lights", "lighting"),
        "相机": ("camera", "cameras", "cam"),
        "渲染": ("render", "rendering"),
        "视口": ("viewport", "viewports"),
        "几何": ("geometry", "geo"),
        "曲线": ("curve", "curves", "spline", "splines"),
        "多边形": ("polygon", "polygons", "poly", "mesh"),
        "网格": ("mesh", "grid", "geometry"),
        "实例": ("instance", "instances", "instancing"),
        "复制": ("copy", "duplicate", "clone", "copytopoints"),
        "散布": ("scatter", "scatter_points", "points"),
        "地形": ("heightfield", "terrain"),
        "体积": ("volume", "volumes", "vdb"),
        "烟雾": ("smoke", "pyro", "volume"),
        "火焰": ("fire", "flame", "pyro"),
        "流体": ("fluid", "fluids", "flip"),
        "粒子": ("particle", "particles", "pop"),
        "刚体": ("rigidbody", "rigid", "rbd"),
        "约束": ("constraint", "constraints"),
        "碰撞": ("collision", "collider", "collisions"),
        "模拟": ("simulation", "simulate", "sim"),
        "解算器": ("solver", "solvers", "solve"),
        "动画": ("animation", "animate", "anim"),
        "表达式": ("expression", "expressions", "expr"),
        "脚本": ("script", "scripts", "python"),
        "代码": ("code", "script", "vex", "python"),
        "包装盒": ("bbox", "boundingbox", "bounding_box"),
        "变换": ("transform", "translate", "rotate", "scale"),
        "移动": ("move", "translate", "transform"),
        "旋转": ("rotate", "rotation", "transform"),
        "缩放": ("scale", "scaling", "transform"),
        "函数": ("function", "functions"),
        "工具": ("tool", "tools"),
        "文档": ("document", "documents", "doc", "docs"),
        "记忆": ("memory", "memories"),
        "搜索": ("search", "find", "query"),
        "创建": ("create", "make", "build", "add"),
        "删除": ("delete", "remove", "destroy"),
        "修改": ("modify", "edit", "change", "update"),
        "设置": ("set", "assign", "configure"),
        "获取": ("get", "fetch", "read", "inspect"),
        "连接": ("connect", "wire", "link"),
        "断开": ("disconnect", "unlink", "unwire"),
        "合并": ("merge", "combine", "join"),
        "分离": ("split", "separate", "detach"),
        "布局": ("layout", "arrange"),
        "显示": ("display", "show", "visible"),
        "隐藏": ("hide", "hidden", "invisible"),
        "启用": ("enable", "activate", "on"),
        "禁用": ("disable", "deactivate", "off"),
        "导入": ("import", "load"),
        "导出": ("export", "save", "write"),
        "保存": ("save", "write", "export"),
        "加载": ("load", "import", "read"),
        "缓存": ("cache", "caching"),
        "烘焙": ("bake", "baking"),
        "循环": ("loop", "foreach", "for_each", "iterate"),
        "随机": ("random", "rand", "stochastic"),
        "噪声": ("noise", "noises", "random"),
        "平滑": ("smooth", "smoothing", "blur"),
        "细分": ("subdivide", "subdivision", "subdiv"),
        "错误": ("error", "errors", "warning", "warnings"),
        "警告": ("warning", "warnings", "warn"),
        "日志": ("log", "logs", "logging"),
        "诊断": ("diagnostic", "diagnostics", "debug"),
        "测试": ("test", "tests", "testing"),
        "规则": ("rule", "rules"),
        "计划": ("plan", "planning"),
        "任务": ("task", "tasks", "job", "jobs"),
        "步骤": ("step", "steps"),
        "结果": ("result", "results", "output"),
        "输入": ("input", "inputs"),
        "输出": ("output", "outputs"),
        "模式": ("mode", "modes", "pattern", "patterns"),
    }
    _ALIAS_LOOKUP = {}
    for _canonical_alias, _equivalent_aliases in _BILINGUAL_ALIASES.items():
        _alias_group = (_canonical_alias,) + _equivalent_aliases
        for _alias in _alias_group:
            _ALIAS_LOOKUP[_alias] = _alias_group

    def _tokenize_bilingual(self, text: str) -> List[Tuple[str, float]]:
        """双语分词：CJK n-gram、英文词/子词、常用中英领域别名。

        Returns:
            List of (token, weight) tuples
        """
        tokens: List[Tuple[str, float]] = []
        text_lower = text.lower()

        # 按 CJK 区段切分为交替的 [非CJK, CJK, 非CJK, ...] 段
        segments = self._CJK_RE.split(text_lower)
        cjk_parts = self._CJK_RE.findall(text_lower)

        # 重建交错列表：[seg0, cjk0, seg1, cjk1, ...]
        interleaved: List[Tuple[str, bool]] = []
        for i, seg in enumerate(segments):
            if seg:
                interleaved.append((seg, False))
            if i < len(cjk_parts):
                interleaved.append((cjk_parts[i], True))

        for seg, is_cjk in interleaved:
            if is_cjk:
                # CJK 段：unigram + bigram + trigram
                for ch in seg:
                    tokens.append((ch, 2.0))
                for i in range(len(seg) - 1):
                    tokens.append((seg[i:i+2], 3.0))
                for i in range(len(seg) - 2):
                    tokens.append((seg[i:i+3], 1.5))

                for alias, equivalents in self._BILINGUAL_ALIASES.items():
                    if alias in seg:
                        for equivalent in equivalents:
                            tokens.append((f"alias:{equivalent}", 2.5))
            else:
                # 非 CJK 段：完整英文词 + 前后缀子词 + 字符 bigram
                for m in self._EN_WORD_RE.finditer(seg):
                    w = m.group()
                    if len(w) < 2:
                        continue
                    tokens.append((w, 3.0))
                    for alias in self._ALIAS_LOOKUP.get(w, ())[1:]:
                        tokens.append((f"alias:{alias}", 2.5))
                    if len(w) >= 4:
                        tokens.append((w[:3], 1.0))   # prefix
                        tokens.append((w[-3:], 1.0))  # suffix
                    for i in range(len(w) - 1):
                        tokens.append((w[i:i+2], 0.5))

        return tokens

    def _encode_fallback(self, text: str) -> np.ndarray:
        """双语词法哈希向量。

        使用 double hashing（MD5 + SHA1）减少碰撞，
        CJK n-gram、英文完整词、常用中英领域别名加权。
        """
        vec = np.zeros(self.dim, dtype=np.float32)
        text_clean = text.strip()
        if not text_clean:
            return vec

        for token, weight in self._tokenize_bilingual(text_clean):
            encoded = token.encode('utf-8')
            # 主哈希位置
            h1 = int(hashlib.md5(encoded).hexdigest(), 16) % self.dim
            vec[h1] += weight
            # 副哈希位置（减少碰撞，权重减半）
            h2 = int(hashlib.sha1(encoded).hexdigest(), 16) % self.dim
            vec[h2] += weight * 0.5

        return vec

    # ==========================================================
    # 相似度计算
    # ==========================================================

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """计算两个向量的余弦相似度

        向量已归一化时等价于点积。
        """
        if a is None or b is None:
            return 0.0
        dot = np.dot(a, b)
        return float(np.clip(dot, -1.0, 1.0))

    @staticmethod
    def batch_cosine_similarity(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        """计算 query 与矩阵中每行的余弦相似度

        Args:
            query: shape=(dim,) 查询向量（已归一化）
            matrix: shape=(n, dim) 候选向量矩阵（已归一化）

        Returns:
            shape=(n,) 相似度数组
        """
        if query is None or matrix is None or len(matrix) == 0:
            return np.array([], dtype=np.float32)
        scores = matrix @ query
        return np.clip(scores, -1.0, 1.0)

    # ==========================================================
    # 序列化辅助
    # ==========================================================

    @staticmethod
    def to_bytes(vec: np.ndarray) -> bytes:
        """将向量序列化为 bytes（存入 SQLite BLOB）"""
        return vec.astype(np.float32).tobytes()

    @staticmethod
    def from_bytes(data: bytes, dim: int = EMBEDDING_DIM) -> np.ndarray:
        """从 bytes 反序列化为向量"""
        if not data:
            return np.zeros(dim, dtype=np.float32)
        return np.frombuffer(data, dtype=np.float32).copy()


# ============================================================
# 全局单例
# ============================================================

def get_embedder(model_name: str = DEFAULT_MODEL) -> LocalEmbedder:
    """获取全局 Embedding 编码器实例（单例）"""
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = LocalEmbedder(model_name)
    return _embedder_instance
