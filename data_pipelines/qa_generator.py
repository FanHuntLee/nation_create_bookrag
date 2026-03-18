"""
QA 数据集构建流水线 —— QA 生成模块

负责：
  1. 根据 SampledChunkGroup 构造对应的 LLM Prompt
  2. 并发调用 LLM 生成 question + answer
  3. 对输出结果做格式校验与重试
  4. 组装最终的 QA 样本字典
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from data_pipelines.chunk_sampler import SampledChunkGroup, get_section_path
from data_pipelines.prompts import (
    SINGLE_TEXT_QA_PROMPT,
    SINGLE_TABLE_QA_PROMPT,
    SINGLE_IMAGE_QA_PROMPT,
    SINGLE_TITLE_QA_PROMPT,
    MULTI_CHUNK_QA_PROMPT,
    format_chunk_for_prompt,
)

log = logging.getLogger(__name__)

MAX_RETRY = 2  # 单条 QA 生成失败时最大重试次数


# ──────────────────────────────────────────────
# Prompt 构造
# ──────────────────────────────────────────────

def _build_single_prompt(
    group: SampledChunkGroup,
    doc_name: str,
    id2node: Dict[int, dict],
) -> str:
    """为单 chunk 分组构造 Prompt。"""
    node = group.nodes[0]
    meta = node.get("meta_info", {})
    chunk_type = group.chunk_types[0] if group.chunk_types else "text"
    page_idx = meta.get("page_idx")
    page_display = int(page_idx) + 1 if page_idx is not None else "?"
    section_path = get_section_path(node, id2node)
    qt = group.question_type
    diff = group.difficulty

    if chunk_type == "table":
        table_body = meta.get("table_body") or ""
        caption = meta.get("caption") or "（无标题）"
        return SINGLE_TABLE_QA_PROMPT.substitute(
            doc_name=doc_name,
            page_idx=page_display,
            caption=caption,
            table_body=table_body,
            question_type=qt,
            difficulty=diff,
        )

    if chunk_type == "image":
        caption = meta.get("caption") or "（无标题）"
        summary = node.get("summary") or "（无摘要）"
        return SINGLE_IMAGE_QA_PROMPT.substitute(
            doc_name=doc_name,
            page_idx=page_display,
            caption=caption,
            summary=summary,
            question_type=qt,
            difficulty=diff,
        )

    if chunk_type == "title":
        title_text = meta.get("content") or ""
        summary = node.get("summary") or "（无摘要）"
        title_level = meta.get("title_level", 0)
        return SINGLE_TITLE_QA_PROMPT.substitute(
            doc_name=doc_name,
            page_idx=page_display,
            title_level=title_level,
            title_text=title_text,
            summary=summary,
            difficulty=diff,
        )

    # 默认：文本节点
    content = meta.get("content") or ""
    return SINGLE_TEXT_QA_PROMPT.substitute(
        doc_name=doc_name,
        page_idx=page_display,
        section_path=section_path,
        content=content,
        question_type=qt,
        difficulty=diff,
    )


def _build_multi_prompt(group: SampledChunkGroup, doc_name: str) -> str:
    """为多 chunk 分组构造 Prompt。"""
    chunk_texts = []
    pages = []
    for idx, node in enumerate(group.nodes):
        chunk_texts.append(format_chunk_for_prompt(node, idx))
        page_idx = node.get("meta_info", {}).get("page_idx")
        if page_idx is not None:
            pages.append(int(page_idx) + 1)

    multi_content = "\n\n".join(chunk_texts)
    if pages:
        page_range = f"{min(pages)}-{max(pages)}" if len(pages) > 1 else str(pages[0])
    else:
        page_range = "?"

    return MULTI_CHUNK_QA_PROMPT.substitute(
        doc_name=doc_name,
        multi_chunk_content=multi_content,
        chunk_count=len(group.nodes),
        page_range=page_range,
        question_type=group.question_type,
        difficulty=group.difficulty,
    )


# ──────────────────────────────────────────────
# LLM 调用 & 解析
# ──────────────────────────────────────────────

def _extract_json(raw: str) -> Optional[Dict[str, str]]:
    """
    从 LLM 输出中提取 JSON 对象 {"question": ..., "answer": ...}。
    支持：纯 JSON、markdown ```json``` 包裹、含少量前后缀文字。
    """
    # 去除 markdown 代码块
    raw = re.sub(r"```(?:json)?", "", raw).strip()

    # 尝试找第一个 { ... } 块
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return None
    try:
        obj = json.loads(raw[start:end])
        if "question" in obj and "answer" in obj:
            return obj
    except json.JSONDecodeError:
        pass

    # 尝试用正则提取 question / answer
    q_match = re.search(r'"question"\s*:\s*"([^"]+)"', raw)
    a_match = re.search(r'"answer"\s*:\s*"([^"]+)"', raw)
    if q_match and a_match:
        return {"question": q_match.group(1), "answer": a_match.group(1)}

    return None


# 用于识别"询问内容位于文档哪一页"的问题模式
_PAGE_LOCATION_RE = re.compile(
    r"位于(?:第)?\s*\d+\s*页"
    r"|在(?:文档|文件|说明书|手册)?的?第?\s*\d+\s*页"
    r"|位于哪\s*[一]?\s*页"
    r"|在哪\s*[一]?\s*页"
    r"|第\s*几\s*页"
    r"|哪\s*一\s*页"
    r"|页\s*码\s*是"
)


def _validate_qa(qa: Dict[str, str]) -> bool:
    """校验生成的 QA 对的基本质量。"""
    q = qa.get("question", "").strip()
    a = qa.get("answer", "").strip()
    if len(q) < 5 or len(a) < 5:
        return False
    if q == a:
        return False
    # 过滤询问页码位置的问题（此类问题无 RAG 价值）
    if _PAGE_LOCATION_RE.search(q) or _PAGE_LOCATION_RE.search(a):
        return False
    # 问题应以问号结尾（中文或英文）
    if not (q.endswith("？") or q.endswith("?") or q.endswith("。")):
        # 宽松处理：只要长度合理就接受
        if len(q) < 8:
            return False
    return True


def _call_llm_with_retry(
    llm_controller,
    prompt: str,
    max_retry: int = MAX_RETRY,
) -> Optional[Dict[str, str]]:
    """调用 LLM 并重试，返回解析后的 QA 字典，失败返回 None。"""
    for attempt in range(max_retry + 1):
        try:
            raw = llm_controller.get_completion(prompt)
            qa = _extract_json(raw)
            if qa and _validate_qa(qa):
                return qa
            log.debug("第 %d 次尝试解析失败，原始输出：%s", attempt + 1, raw[:200])
        except Exception as e:
            log.warning("第 %d 次 LLM 调用异常：%s", attempt + 1, e)
    return None


# ──────────────────────────────────────────────
# QA 样本组装
# ──────────────────────────────────────────────

def _assemble_sample(
    group: SampledChunkGroup,
    qa: Dict[str, str],
    doc_uuid: str,
    doc_path: str,
) -> Dict[str, Any]:
    """将 SampledChunkGroup + QA 对组装成最终数据集样本字典。"""
    evidences = []
    for node in group.nodes:
        meta = node.get("meta_info", {})
        page_idx = meta.get("page_idx")
        page_display = int(page_idx) + 1 if page_idx is not None else None
        chunk_type = next(
            (ct for ct in group.chunk_types if len(group.nodes) == 1),
            None,
        )
        if chunk_type is None:
            from data_pipelines.chunk_sampler import _get_chunk_type
            chunk_type = _get_chunk_type(node)

        # 提取节点可读内容
        content_for_evidence = ""
        if "TABLE" in node.get("type", ""):
            content_for_evidence = meta.get("caption") or meta.get("table_body") or ""
            content_for_evidence = content_for_evidence[:500]
        elif "IMAGE" in node.get("type", ""):
            caption = meta.get("caption") or ""
            summary = node.get("summary") or ""
            content_for_evidence = f"{caption} | {summary}"
            content_for_evidence = content_for_evidence[:300]
        else:
            content_for_evidence = meta.get("content") or ""
            content_for_evidence = content_for_evidence[:500]

        evidences.append(
            {
                "chunk_id": node["index_id"],
                "chunk_type": chunk_type,
                "page_idx": page_display,
                "content": content_for_evidence,
            }
        )

    return {
        "question": qa["question"].strip(),
        "answer": qa["answer"].strip(),
        "chunk_ids": [n["index_id"] for n in group.nodes],
        "evidences": evidences,
        "doc_uuid": doc_uuid,
        "doc_path": doc_path,
        "question_type": group.question_type,
        "difficulty": group.difficulty,
        "chunk_types": group.chunk_types,
        "is_multi_chunk": len(group.nodes) > 1,
        "grouping_method": group.grouping_method,
    }


# ──────────────────────────────────────────────
# 主类：QAGenerator
# ──────────────────────────────────────────────

class QAGenerator:
    """
    接收 SampledChunkGroup 列表，并发调用 LLM 生成 QA 样本。
    """

    def __init__(
        self,
        llm_controller,
        doc_uuid: str,
        doc_path: str,
        doc_name: str,
        id2node: Dict[int, dict],
        max_workers: int = 4,
    ):
        self.llm = llm_controller
        self.doc_uuid = doc_uuid
        self.doc_path = doc_path
        self.doc_name = doc_name or os.path.basename(doc_path)
        self.id2node = id2node
        self.max_workers = max_workers

    def generate(self, groups: List[SampledChunkGroup]) -> List[Dict[str, Any]]:
        """
        并发生成所有 QA 样本。

        Args:
            groups: 采样分组列表

        Returns:
            成功生成的 QA 样本列表
        """
        results: List[Optional[Dict[str, Any]]] = [None] * len(groups)

        def _process(idx: int, group: SampledChunkGroup):
            if len(group.nodes) == 1:
                prompt = _build_single_prompt(group, self.doc_name, self.id2node)
            else:
                prompt = _build_multi_prompt(group, self.doc_name)

            qa = _call_llm_with_retry(self.llm, prompt)
            if qa is None:
                log.warning("第 %d 条采样（%s）生成失败，跳过", idx, group.grouping_method)
                return idx, None

            sample = _assemble_sample(group, qa, self.doc_uuid, self.doc_path)
            return idx, sample

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(_process, i, g): i for i, g in enumerate(groups)
            }
            done_count = 0
            for future in as_completed(futures):
                idx, sample = future.result()
                results[idx] = sample
                done_count += 1
                if done_count % 10 == 0:
                    success = sum(1 for r in results if r is not None)
                    log.info("进度：%d/%d，已成功 %d 条", done_count, len(groups), success)

        final = [r for r in results if r is not None]
        log.info("QA 生成完成：成功 %d / 总计 %d", len(final), len(groups))
        return final


# ──────────────────────────────────────────────
# 工具：去重 & 比例验证
# ──────────────────────────────────────────────

def deduplicate_questions(samples: List[Dict[str, Any]], threshold: float = 0.7) -> List[Dict[str, Any]]:
    """
    基于 Jaccard 字符级相似度去除重复问题。

    Args:
        samples: QA 样本列表
        threshold: 相似度阈值（超过此值认为重复）

    Returns:
        去重后的样本列表
    """
    def jaccard(a: str, b: str) -> float:
        sa, sb = set(a), set(b)
        inter = len(sa & sb)
        union = len(sa | sb)
        return inter / union if union > 0 else 0.0

    kept = []
    kept_questions = []
    for s in samples:
        q = s["question"]
        is_dup = any(jaccard(q, kq) >= threshold for kq in kept_questions)
        if not is_dup:
            kept.append(s)
            kept_questions.append(q)

    removed = len(samples) - len(kept)
    if removed > 0:
        log.info("去重：移除 %d 条重复问题，剩余 %d 条", removed, len(kept))
    return kept


def print_distribution_report(samples: List[Dict[str, Any]]) -> None:
    """打印数据集各维度的分布统计。"""
    if not samples:
        print("数据集为空，无分布信息")
        return

    n = len(samples)

    def count_dist(key: str) -> Dict[str, float]:
        from collections import Counter
        c = Counter(s[key] for s in samples)
        return {k: round(v / n, 3) for k, v in sorted(c.items())}

    def count_list_dist(key: str) -> Dict[str, float]:
        from collections import Counter
        c = Counter()
        for s in samples:
            for item in s.get(key, []):
                c[item] += 1
        total = sum(c.values())
        return {k: round(v / total, 3) for k, v in sorted(c.items())}

    print(f"\n{'='*50}")
    print(f"QA 数据集分布报告（共 {n} 条）")
    print(f"{'='*50}")
    print(f"问题类型分布：{count_dist('question_type')}")
    print(f"难度分布：    {count_dist('difficulty')}")
    print(f"Chunk 类型分布（含多 chunk）：{count_list_dist('chunk_types')}")
    single = sum(1 for s in samples if not s["is_multi_chunk"])
    multi = n - single
    print(f"单/多 chunk：单={single}（{single/n:.1%}），多={multi}（{multi/n:.1%}）")
    methods = {}
    for s in samples:
        m = s.get("grouping_method", "unknown")
        methods[m] = methods.get(m, 0) + 1
    print(f"分组方法分布：{methods}")
    print(f"{'='*50}\n")
