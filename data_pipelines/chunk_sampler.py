"""
QA 数据集构建流水线 —— Chunk 采样模块

支持两种多 chunk 分组策略：
  1. tree：基于文档树的父子/兄弟关系分组（快速、无需额外 LLM 调用）
  2. llm_semantic：调用 LLM 对批量 chunk 做语义分组（质量更高，适合跨章节问题）
"""

import json
import random
import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# 内容质量过滤相关正则
# ──────────────────────────────────────────────

# 目录点导线：". .59" 或 "...62" 等（点或空格序列后跟数字）
_TOC_DOTS_RE = re.compile(r'[\.\s]{2,}\d')
# 超过两处点导线组合 -> 基本确定是目录
_TOC_MULTI_RE = re.compile(r'(\.\s*\..*?){2,}')
# 页眉/页脚样板：URL + 邮箱同时出现
_URL_EMAIL_RE = re.compile(r'(?:www\.\S+|https?://\S+|\S+@\S+\.\w{2,})')


def _is_toc_content(content: str) -> bool:
    """检测内容是否为目录条目（含 '. .页码' 形式的点导线）。"""
    if not content:
        return False
    # 有多个点导线段，且整体较短（典型目录行）
    if _TOC_MULTI_RE.search(content):
        return True
    # 或：内容很短，且含有点导线+数字
    if len(content) < 80 and _TOC_DOTS_RE.search(content):
        dot_chars = len(re.findall(r'[\.\s]', content))
        if dot_chars / max(len(content), 1) > 0.25:
            return True
    return False


def _is_boilerplate_content(content: str) -> bool:
    """检测内容是否为页眉页脚样板（公司信息行、页码行等）。"""
    if not content:
        return False
    # 含有 2 个及以上 URL / 邮箱 -> 典型的公司联系信息行
    if len(_URL_EMAIL_RE.findall(content)) >= 2:
        return True
    # 极短且全为数字/斜杠/空格 -> 纯页码行
    stripped = content.strip()
    if len(stripped) < 20 and re.match(r'^[\d\s/\\-]+$', stripped):
        return True
    return False


# ──────────────────────────────────────────────
# 数据类型定义
# ──────────────────────────────────────────────

@dataclass
class RatioConfig:
    """各维度的目标采样比例配置。"""
    single_chunk: float = 0.6
    multi_chunk: float = 0.4

    type_text: float = 0.50
    type_table: float = 0.25
    type_image: float = 0.15
    type_title: float = 0.10

    factual: float = 0.35
    reasoning: float = 0.30
    numerical: float = 0.20
    structural: float = 0.15

    easy: float = 0.30
    medium: float = 0.40
    hard: float = 0.30

    @classmethod
    def from_dict(cls, d: dict) -> "RatioConfig":
        cfg = cls()
        if "single_chunk" in d:
            cfg.single_chunk = d["single_chunk"]
        if "multi_chunk" in d:
            cfg.multi_chunk = d["multi_chunk"]
        type_d = d.get("type", {})
        if "text" in type_d:
            cfg.type_text = type_d["text"]
        if "table" in type_d:
            cfg.type_table = type_d["table"]
        if "image" in type_d:
            cfg.type_image = type_d["image"]
        if "title" in type_d:
            cfg.type_title = type_d["title"]
        qt_d = d.get("question_type", {})
        if "factual" in qt_d:
            cfg.factual = qt_d["factual"]
        if "reasoning" in qt_d:
            cfg.reasoning = qt_d["reasoning"]
        if "numerical" in qt_d:
            cfg.numerical = qt_d["numerical"]
        if "structural" in qt_d:
            cfg.structural = qt_d["structural"]
        diff_d = d.get("difficulty", {})
        if "easy" in diff_d:
            cfg.easy = diff_d["easy"]
        if "medium" in diff_d:
            cfg.medium = diff_d["medium"]
        if "hard" in diff_d:
            cfg.hard = diff_d["hard"]
        return cfg


@dataclass
class SampledChunkGroup:
    """一个采样结果（单 chunk 或多 chunk 的分组）。"""
    nodes: List[dict]                      # 参与的节点列表（来自 tree.json）
    question_type: str                     # factual / reasoning / numerical / structural
    difficulty: str                        # easy / medium / hard
    grouping_method: str                   # single / tree_sibling / tree_parent_child / tree_cross_section / llm_semantic
    chunk_types: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.chunk_types:
            self.chunk_types = list({_get_chunk_type(n) for n in self.nodes})


# ──────────────────────────────────────────────
# 内部工具函数
# ──────────────────────────────────────────────

def _get_chunk_type(node: dict) -> str:
    t = node.get("type", "")
    if "TABLE" in t:
        return "table"
    if "IMAGE" in t:
        return "image"
    if "TITLE" in t:
        return "title"
    if "TEXT" in t or t == "":
        return "text"
    return "text"


def _is_valid_node(node: dict) -> bool:
    """检查节点是否含有足够的内容可供出题。"""
    if node.get("type") in ("root", "NodeType.ROOT"):
        return False
    meta = node.get("meta_info", {})
    t = node.get("type", "")
    if "IMAGE" in t:
        has_content = bool(meta.get("caption")) or bool(node.get("summary"))
        return has_content
    if "TABLE" in t:
        return bool(meta.get("table_body")) or bool(meta.get("caption"))
    if "TITLE" in t:
        content = meta.get("content") or ""
        return len(content.strip()) > 3
    content = meta.get("content") or ""
    if len(content.strip()) < 20:
        return False
    # 过滤目录条目（含点导线）和页眉页脚样板内容
    if _is_toc_content(content):
        return False
    if _is_boilerplate_content(content):
        return False
    return True


def _node_has_numbers(node: dict) -> bool:
    """粗略判断节点内容是否包含数值，用于决定是否适合 numerical 类型。"""
    meta = node.get("meta_info", {})
    text = (meta.get("content") or "") + (meta.get("table_body") or "") + (node.get("summary") or "")
    return any(c.isdigit() for c in text)


def _dedup_pool(pool: List[dict]) -> List[dict]:
    """
    对 pool 中的节点按正文内容去重：
    归一化（去除空白后转小写）完全相同的内容只保留首次出现的节点。
    """
    seen: set = set()
    result = []
    for node in pool:
        meta = node.get("meta_info", {})
        raw = (
            meta.get("content")
            or meta.get("table_body")
            or meta.get("caption")
            or node.get("summary")
            or ""
        )
        normalized = re.sub(r"\s+", " ", raw).strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(node)
    removed = len(pool) - len(result)
    if removed > 0:
        log.info("内容去重：移除 %d 个重复节点", removed)
    return result


def _weighted_sample(pool: List, weights: List[float], k: int) -> List:
    """带权重的无放回采样（k > len(pool) 时取全部）。"""
    if k >= len(pool):
        return list(pool)
    chosen = random.choices(pool, weights=weights, k=k * 3)
    seen = set()
    result = []
    for item in chosen:
        item_id = item["index_id"]
        if item_id not in seen:
            seen.add(item_id)
            result.append(item)
            if len(result) == k:
                break
    if len(result) < k:
        remaining = [x for x in pool if x["index_id"] not in seen]
        result += remaining[: k - len(result)]
    return result


def _assign_question_labels(
    node: dict,
    chunk_type: str,
    ratio: RatioConfig,
) -> Tuple[str, str]:
    """
    为单个 chunk 按配置比例加权随机分配 question_type 和 difficulty。
    只做一次性加权随机，不追踪全局使用量。
    """
    qt_weights = {
        "factual": ratio.factual,
        "reasoning": ratio.reasoning,
        "numerical": ratio.numerical,
        "structural": ratio.structural,
    }
    # 按节点类型微调权重（不适合的类型降为 0）
    if chunk_type == "image":
        qt_weights["numerical"] = 0.0
    if chunk_type == "title":
        qt_weights["structural"] *= 2.0
    if chunk_type == "table":
        qt_weights["numerical"] *= 1.5
    if not _node_has_numbers(node):
        qt_weights["numerical"] *= 0.5

    qt_keys = list(qt_weights.keys())
    qt_vals = [max(qt_weights[k], 0.0) for k in qt_keys]
    question_type = random.choices(qt_keys, weights=qt_vals, k=1)[0]

    # difficulty：单 chunk 不分配 hard（hard 留给多 chunk）
    diff_weights = {"easy": ratio.easy, "medium": ratio.medium, "hard": 0.0}
    diff_keys = list(diff_weights.keys())
    diff_vals = [diff_weights[k] for k in diff_keys]
    difficulty = random.choices(diff_keys, weights=diff_vals, k=1)[0]

    return question_type, difficulty


# ──────────────────────────────────────────────
# 主类：ChunkSampler
# ──────────────────────────────────────────────

class ChunkSampler:
    """
    从 tree.json 的节点列表中进行多维度采样，
    返回 SampledChunkGroup 列表。
    """

    def __init__(
        self,
        nodes: List[dict],
        ratio: Optional[RatioConfig] = None,
        seed: int = 42,
    ):
        self.nodes = nodes
        self.ratio = ratio or RatioConfig()
        random.seed(seed)

        # 建立索引
        self.id2node: Dict[int, dict] = {n["index_id"]: n for n in nodes}
        self.children: Dict[int, List[int]] = {}
        for n in nodes:
            pid = n.get("parent_id")
            if pid is not None:
                self.children.setdefault(pid, []).append(n["index_id"])

        # 分类有效节点
        self.text_pool: List[dict] = []
        self.table_pool: List[dict] = []
        self.image_pool: List[dict] = []
        self.title_pool: List[dict] = []
        for n in nodes:
            if not _is_valid_node(n):
                continue
            ct = _get_chunk_type(n)
            if ct == "text":
                self.text_pool.append(n)
            elif ct == "table":
                self.table_pool.append(n)
            elif ct == "image":
                self.image_pool.append(n)
            elif ct == "title":
                self.title_pool.append(n)

        # 对各 pool 做内容级去重
        self.text_pool = _dedup_pool(self.text_pool)
        self.table_pool = _dedup_pool(self.table_pool)
        self.image_pool = _dedup_pool(self.image_pool)
        self.title_pool = _dedup_pool(self.title_pool)

        log.info(
            "ChunkSampler 初始化（去重后）：text=%d, table=%d, image=%d, title=%d",
            len(self.text_pool), len(self.table_pool),
            len(self.image_pool), len(self.title_pool),
        )

    # ── 单 Chunk 采样 ──────────────────────────

    def sample_single_chunks(self, n_total: int) -> List[SampledChunkGroup]:
        """按比例采样单 chunk 组。"""
        r = self.ratio
        targets = {
            "text": max(1, round(n_total * r.type_text)),
            "table": max(0, round(n_total * r.type_table)),
            "image": max(0, round(n_total * r.type_image)),
            "title": max(0, round(n_total * r.type_title)),
        }
        # 如果某类 pool 不足，重新分配给 text
        for ct in ("table", "image", "title"):
            pool = getattr(self, f"{ct}_pool")
            if len(pool) < targets[ct]:
                deficit = targets[ct] - len(pool)
                targets[ct] = len(pool)
                targets["text"] += deficit
                log.warning("%s pool 不足，将 %d 个配额转移到 text", ct, deficit)

        results: List[SampledChunkGroup] = []

        for ct, quota in targets.items():
            pool: List[dict] = getattr(self, f"{ct}_pool")
            sampled = random.sample(pool, min(quota, len(pool)))
            for node in sampled:
                qt, diff = _assign_question_labels(node, ct, self.ratio)
                results.append(
                    SampledChunkGroup(
                        nodes=[node],
                        question_type=qt,
                        difficulty=diff,
                        grouping_method="single",
                        chunk_types=[ct],
                    )
                )

        log.info("单 chunk 采样完成：%d 条", len(results))
        return results

    # ── 多 Chunk 采样：树结构分组 ──────────────

    def sample_multi_chunks_tree(self, n_total: int) -> List[SampledChunkGroup]:
        """
        利用树的父子/兄弟关系构建多 chunk 分组，
        采样约 n_total 个分组。
        """
        groups: List[SampledChunkGroup] = []

        sibling_groups = self._get_sibling_groups()
        parent_child_groups = self._get_parent_child_groups()
        cross_section_groups = self._get_cross_section_groups()

        # 三种来源混合，各占约 1/3
        quota_each = max(1, n_total // 3)

        random.shuffle(sibling_groups)
        random.shuffle(parent_child_groups)
        random.shuffle(cross_section_groups)

        sources = [
            (sibling_groups[:quota_each], "tree_sibling"),
            (parent_child_groups[:quota_each], "tree_parent_child"),
            (cross_section_groups[:n_total - 2 * quota_each], "tree_cross_section"),
        ]

        for node_list, method in sources:
            for nodes in node_list:
                if not nodes:
                    continue
                qt = self._pick_multi_qt(nodes)
                diff = self._pick_multi_diff()
                groups.append(
                    SampledChunkGroup(
                        nodes=nodes,
                        question_type=qt,
                        difficulty=diff,
                        grouping_method=method,
                    )
                )

        log.info("树结构多 chunk 采样完成：%d 条", len(groups))
        return groups

    def _get_sibling_groups(self) -> List[List[dict]]:
        """同一父节点下的兄弟节点分组（2-4 个子节点）。"""
        groups = []
        for parent_id, child_ids in self.children.items():
            parent = self.id2node.get(parent_id)
            if parent is None:
                continue
            # 只关注 TITLE 节点下的子节点
            if "TITLE" not in parent.get("type", "") and parent.get("type") != "root":
                continue
            valid_children = [
                self.id2node[cid]
                for cid in child_ids
                if cid in self.id2node and _is_valid_node(self.id2node[cid])
                and "TITLE" not in self.id2node[cid].get("type", "")
            ]
            if len(valid_children) < 2:
                continue
            # 随机取 2-4 个子节点作为一组
            for _ in range(max(1, len(valid_children) // 3)):
                k = min(random.randint(2, 4), len(valid_children))
                groups.append(random.sample(valid_children, k))
        return groups

    def _get_parent_child_groups(self) -> List[List[dict]]:
        """TITLE 节点 + 其直接子节点（TEXT/TABLE/IMAGE，取 1-3 个）。"""
        groups = []
        for n in self.title_pool:
            child_ids = self.children.get(n["index_id"], [])
            valid_children = [
                self.id2node[cid]
                for cid in child_ids
                if cid in self.id2node and _is_valid_node(self.id2node[cid])
                and "TITLE" not in self.id2node[cid].get("type", "")
            ]
            if not valid_children:
                continue
            k = min(random.randint(1, 3), len(valid_children))
            selected = random.sample(valid_children, k)
            groups.append([n] + selected)
        return groups

    def _get_cross_section_groups(self) -> List[List[dict]]:
        """
        跨章节分组：从不同顶级 TITLE 节点各取 1 个代表性子节点。
        """
        root_node = next((n for n in self.nodes if n.get("type") == "root"), None)
        if root_node is None:
            return []
        top_title_ids = self.children.get(root_node["index_id"], [])
        top_titles = [
            self.id2node[tid]
            for tid in top_title_ids
            if tid in self.id2node and "TITLE" in self.id2node[tid].get("type", "")
        ]
        if len(top_titles) < 2:
            return []

        groups = []
        for _ in range(min(20, len(top_titles) * 2)):
            # 随机选 2-3 个顶级章节
            k = min(random.randint(2, 3), len(top_titles))
            chosen_titles = random.sample(top_titles, k)
            rep_nodes = []
            for title in chosen_titles:
                child_ids = self.children.get(title["index_id"], [])
                # 取该章节下的第一个有效 TEXT 节点作为代表
                candidates = [
                    self.id2node[cid]
                    for cid in child_ids
                    if cid in self.id2node
                    and "TEXT" in self.id2node[cid].get("type", "")
                    and _is_valid_node(self.id2node[cid])
                ]
                if candidates:
                    rep_nodes.append(random.choice(candidates))
            if len(rep_nodes) >= 2:
                groups.append(rep_nodes)
        return groups

    def _pick_multi_qt(self, nodes: List[dict]) -> str:
        """多 chunk 按配置比例加权随机分配 question_type，reasoning 权重翻倍。"""
        r = self.ratio
        weights = {
            "factual": r.factual,
            "reasoning": r.reasoning * 2.0,   # 多 chunk 更适合 reasoning
            "numerical": r.numerical,
            "structural": r.structural,
        }
        if any("TABLE" in n.get("type", "") for n in nodes):
            weights["numerical"] *= 1.5
        keys = list(weights.keys())
        vals = [weights[k] for k in keys]
        return random.choices(keys, weights=vals, k=1)[0]

    def _pick_multi_diff(self) -> str:
        """多 chunk 按配置比例加权随机分配 difficulty，偏向 medium/hard。"""
        r = self.ratio
        weights = {"easy": r.easy * 0.4, "medium": r.medium, "hard": r.hard * 1.5}
        keys = list(weights.keys())
        vals = [weights[k] for k in keys]
        return random.choices(keys, weights=vals, k=1)[0]

    # ── 多 Chunk 采样：LLM 语义分组 ───────────

    def sample_multi_chunks_llm(
        self,
        n_total: int,
        llm_controller,
        batch_size: int = 40,
        min_groups: int = 5,
        max_groups: int = 12,
    ) -> List[SampledChunkGroup]:
        """
        调用 LLM 对批量 chunk 做语义分组，返回多 chunk 分组采样结果。

        Args:
            n_total: 目标分组数量
            llm_controller: BaseLLMController 实例（来自 Core.provider.llm）
            batch_size: 每批送入 LLM 的 chunk 数
            min_groups: 每批 LLM 分组 Prompt 要求的最少分组数
            max_groups: 每批 LLM 分组 Prompt 要求的最多分组数
        """
        from data_pipelines.prompts import (
            LLM_SEMANTIC_GROUPING_PROMPT,
            format_chunk_summary_for_grouping,
        )

        all_valid = [n for n in (self.text_pool + self.table_pool) if _is_valid_node(n)]
        if len(all_valid) < 4:
            log.warning("有效节点不足 4 个，跳过 LLM 语义分组")
            return []

        results: List[SampledChunkGroup] = []
        attempts = 0
        max_attempts = max(3, (n_total // min_groups) + 2)

        while len(results) < n_total and attempts < max_attempts:
            attempts += 1
            batch = random.sample(all_valid, min(batch_size, len(all_valid)))
            chunk_summaries = "\n".join(
                format_chunk_summary_for_grouping(n) for n in batch
            )
            prompt = LLM_SEMANTIC_GROUPING_PROMPT.substitute(
                chunk_summaries=chunk_summaries,
                min_groups=min_groups,
                max_groups=max_groups,
            )
            try:
                raw = llm_controller.get_completion(prompt)
                raw = raw.strip()
                # 提取 JSON 数组
                start = raw.find("[")
                end = raw.rfind("]") + 1
                if start == -1 or end == 0:
                    log.warning("LLM 分组输出不含 JSON 数组，跳过本批次")
                    continue
                groups_json = json.loads(raw[start:end])
            except Exception as e:
                log.warning("LLM 分组解析失败（%s），跳过本批次", e)
                continue

            batch_id2node = {n["index_id"]: n for n in batch}
            for item in groups_json:
                ids = item.get("group", [])
                if not (2 <= len(ids) <= 4):
                    continue
                nodes = [batch_id2node[i] for i in ids if i in batch_id2node]
                if len(nodes) < 2:
                    continue
                qt = self._pick_multi_qt(nodes)
                diff = self._pick_multi_diff()
                results.append(
                    SampledChunkGroup(
                        nodes=nodes,
                        question_type=qt,
                        difficulty=diff,
                        grouping_method="llm_semantic",
                    )
                )
                if len(results) >= n_total:
                    break

        log.info("LLM 语义分组采样完成：%d 条（目标 %d）", len(results), n_total)
        return results

    # ── 汇总入口 ──────────────────────────────

    def sample(
        self,
        num_samples: int,
        grouping_method: str = "tree",
        llm_controller=None,
    ) -> List[SampledChunkGroup]:
        """
        主采样入口。

        Args:
            num_samples: 总目标采样数
            grouping_method: "tree" 或 "llm_semantic"（后者需提供 llm_controller）
            llm_controller: LLM 控制器（仅 llm_semantic 模式需要）

        Returns:
            List[SampledChunkGroup]
        """
        n_single = round(num_samples * self.ratio.single_chunk)
        n_multi = num_samples - n_single

        single_groups = self.sample_single_chunks(n_single)

        if grouping_method == "llm_semantic":
            if llm_controller is None:
                raise ValueError("llm_semantic 分组模式需要提供 llm_controller")
            multi_groups = self.sample_multi_chunks_llm(n_multi, llm_controller)
        else:
            multi_groups = self.sample_multi_chunks_tree(n_multi)

        all_groups = single_groups + multi_groups
        random.shuffle(all_groups)

        log.info(
            "采样完成：总计 %d 条（单 chunk=%d，多 chunk=%d）",
            len(all_groups), len(single_groups), len(multi_groups),
        )
        return all_groups


# ──────────────────────────────────────────────
# 加载 tree.json
# ──────────────────────────────────────────────

def load_tree_json(tree_json_path: str) -> Tuple[List[dict], str]:
    """
    加载 tree.json，返回 (nodes 列表, doc_path)。
    doc_path 从根节点的 meta_info.file_path 中提取。
    """
    with open(tree_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    nodes: List[dict] = data.get("nodes", [])
    doc_path = ""
    for n in nodes:
        if n.get("type") == "root":
            doc_path = n.get("meta_info", {}).get("file_path") or ""
            break

    log.info("加载 tree.json：%d 个节点，doc_path=%s", len(nodes), doc_path)
    return nodes, doc_path


def get_section_path(node: dict, id2node: Dict[int, dict]) -> str:
    """向上回溯，获取节点所在的章节路径字符串（用于 Prompt 中的上下文）。"""
    path_parts = []
    cur = node
    for _ in range(10):
        pid = cur.get("parent_id")
        if pid is None:
            break
        parent = id2node.get(pid)
        if parent is None:
            break
        if "TITLE" in parent.get("type", ""):
            content = parent.get("meta_info", {}).get("content") or ""
            if content:
                path_parts.insert(0, content)
        cur = parent
    return " > ".join(path_parts) if path_parts else "（根节点）"
