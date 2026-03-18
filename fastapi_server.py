"""
FastAPI 服务器：多文档 RAG 检索服务。

检索流程
--------
1. 用 title_summary_vdb 对问题做摘要级文档路由，找出 top-k 个相关 title chunk。
2. 对召回的摘要文本做 Text Reranker 重排，取 top rerank_topk（默认 5）。
3. 从重排后的 chunk 的 metadata.file_name 中去重，取前 max_doc 个文档。
4. 对每个命中文档懒加载其 GBCRAG Agent（首次加载后缓存），执行纯检索（无 LLM 生成）。
5. 返回所有文档的检索结果列表。

若 title_summary_vdb 未配置或为空，回退到单文档模式（兼容旧行为）。
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ── 项目根目录 ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
import sys
sys.path.insert(0, str(PROJECT_ROOT))

from Core.configs.system_config import load_system_config, SystemConfig
from Core.configs.dataset_config import load_dataset_config, DatasetConfig
from Core.provider.embedding import TextEmbeddingProvider
from Core.provider.vdb import VectorStore
from Core.provider.rerank import TextRerankerProvider
from Core.prompts.gbc_prompt import TEXT_RERANKER_PROMPT
from Core.rag import create_rag_agent
from Core.rag.gbc_rag import GBCRAG
from Core.rag.gbc_utils import GBCRAGContext, SubStep
from Core.rag.gbc_plan import PlanResult
from Core.utils.resource_loader import prepare_rag_dependencies

# ── 日志 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

# ── 配置路径（修改这两项即可切换数据集）────────────────────────────────────────
CONFIG_PATH = PROJECT_ROOT / "config" / "test_minimal.yaml"
DATASET_CONFIG_PATH = "/root/autodl-fs/bookrag/BookRAG/TL3588_data_and_output/TL3588.yaml"

# ── Pydantic 请求/响应模型 ────────────────────────────────────────────────────

class RAGRequest(BaseModel):
    question: str = Field(..., description="待查询的问题")
    title_topk: int = Field(
        default=10,
        ge=1,
        description="摘要 VDB 路由阶段召回的 title chunk 数量",
    )
    rerank_topk: int = Field(
        default=5,
        ge=1,
        description="对召回的摘要做 Text Reranker 重排后保留的 top-k 数量",
    )
    max_doc: int = Field(
        default=3,
        ge=1,
        description="最多对几个文档执行精细图检索",
    )


# ── 全局状态 ──────────────────────────────────────────────────────────────────

_base_config: Optional[SystemConfig] = None
_dataset_cfg: Optional[DatasetConfig] = None

# doc_uuid -> {"doc_path": str, "save_path": str}
_doc_info: Dict[str, dict] = {}

# 已加载的 GBCRAG Agent 缓存（懒加载）
_doc_agents: Dict[str, GBCRAG] = {}

# 多文档摘要路由 VDB
_title_vdb: Optional[VectorStore] = None
_title_embedder: Optional[TextEmbeddingProvider] = None

# 摘要级 Text Reranker（对召回的 title summary 做重排）
_title_reranker: Optional[TextRerankerProvider] = None


# ── 初始化逻辑 ────────────────────────────────────────────────────────────────

def _init_globals() -> None:
    """启动时执行：加载配置、构建文档索引表、初始化路由 VDB 与 Reranker。"""
    global _base_config, _dataset_cfg, _doc_info, _title_vdb, _title_embedder, _title_reranker

    if _base_config is not None:
        return  # 已初始化，跳过

    log.info(f"加载系统配置: {CONFIG_PATH}")
    _base_config = load_system_config(str(CONFIG_PATH))

    log.info(f"加载数据集配置: {DATASET_CONFIG_PATH}")
    _dataset_cfg = load_dataset_config(str(DATASET_CONFIG_PATH))

    # 1. 从数据集 JSON 构建 doc_uuid -> path 映射
    df = pd.read_json(_dataset_cfg.dataset_path)
    if df.empty:
        raise ValueError(f"数据集为空: {_dataset_cfg.dataset_path}")

    for _, row in df.drop_duplicates(subset=["doc_uuid"]).iterrows():
        doc_uuid = str(row["doc_uuid"])
        doc_path = str(row["doc_path"])
        save_path = str(Path(_dataset_cfg.working_dir) / doc_uuid)
        _doc_info[doc_uuid] = {"doc_path": doc_path, "save_path": save_path}

    log.info(f"数据集共 {len(_doc_info)} 个文档: {list(_doc_info.keys())}")

    # 2. 加载 title_summary_vdb（用于多文档路由）
    title_vdb_dir = _dataset_cfg.title_vdb_dir
    if title_vdb_dir is None:
        # 默认路径：working_dir/../title_summary_vdb
        title_vdb_dir = str(Path(_dataset_cfg.working_dir).parent / "title_summary_vdb")

    if not Path(title_vdb_dir).exists():
        log.warning(
            f"title_summary_vdb 目录不存在: {title_vdb_dir}，将回退到单文档模式。"
        )
        return

    collection_name = _dataset_cfg.title_collection_name or "title_summary"

    # 从系统配置获取 embedding 配置（GBC 使用 GBCIndex embedder，与 entity_vdb 同一模型）
    # 直接用 base_config.llm 无关，embedding 来自 GBC index 构建时的 vdb embedding config
    # 此处使用与 build_title_summary_vdb_from_json 相同的配置
    from Core.configs.embedding_config import EmbeddingConfig
    try:
        # 尝试从 system_config 中读取 vdb embedding 配置
        embed_cfg = _base_config.graph.embedding_config
        log.info(f"使用 system_config.graph.embedding_config: {embed_cfg.model_name}")
    except AttributeError:
        log.warning("system_config 中无 graph.embedding_config，使用默认 embedding 配置。")
        embed_cfg = EmbeddingConfig(
            backend="local",
            model_name="/root/autodl-fs/models/Qwen3-Embedding-0.6B",
            device="cuda:0",
            max_length=30000,
        )

    log.info(f"加载 title_summary_vdb: {title_vdb_dir} (collection={collection_name})")
    _title_embedder = TextEmbeddingProvider(
        model_name=embed_cfg.model_name,
        device=embed_cfg.device,
        backend=embed_cfg.backend,
        api_base=getattr(embed_cfg, "api_base", None),
        max_length=getattr(embed_cfg, "max_length", 8192),
    )
    _title_vdb = VectorStore(
        embedding_model=_title_embedder,
        db_path=title_vdb_dir,
        collection_name=collection_name,
    )

    total = _title_vdb.collection.count()
    log.info(f"title_summary_vdb 加载完成，共 {total} 条 title 摘要记录。")
    if total == 0:
        log.warning("title_summary_vdb 为空，将回退到单文档模式。")
        _title_vdb = None
        return

    # 3. 加载摘要级 Text Reranker（参考 Core gbc_retrieval）
    try:
        reranker_cfg = _base_config.rag.strategy_config.reranker_config
    except AttributeError:
        try:
            reranker_cfg = _base_config.graph.reranker_config
        except AttributeError:
            reranker_cfg = None
    if reranker_cfg:
        log.info(f"加载摘要 Reranker: {reranker_cfg.model_name}")
        _title_reranker = TextRerankerProvider(
            model_name=reranker_cfg.model_name,
            max_length=getattr(reranker_cfg, "max_length", 4096),
            device=getattr(reranker_cfg, "device", "cuda:0"),
            backend=getattr(reranker_cfg, "backend", "local"),
            api_base=getattr(reranker_cfg, "api_base", None),
        )
    else:
        log.warning("未找到 reranker 配置，摘要级重排将跳过。")


def _get_or_load_agent(doc_uuid: str) -> GBCRAG:
    """获取或懒加载指定文档的 GBCRAG Agent。"""
    if doc_uuid in _doc_agents:
        return _doc_agents[doc_uuid]

    if doc_uuid not in _doc_info:
        raise ValueError(f"未知文档: {doc_uuid}")

    info = _doc_info[doc_uuid]
    doc_path = info["doc_path"]
    save_path = info["save_path"]

    log.info(f"懒加载文档 Agent: {doc_uuid} (save_path={save_path})")
    current_config = _base_config.model_copy(deep=True)
    current_config.pdf_path = doc_path
    current_config.save_path = save_path

    if current_config.rag.strategy_config.strategy == "gbc":
        current_config.rag.strategy_config.mm_reranker_config.device = "cuda:0"

    dependencies = prepare_rag_dependencies(current_config)
    agent = create_rag_agent(
        strategy_config=current_config.rag.strategy_config,
        llm_config=current_config.llm,
        vlm_config=current_config.vlm,
        **dependencies,
    )

    if not isinstance(agent, GBCRAG):
        raise TypeError(f"文档 {doc_uuid} 的 Agent 不是 GBCRAG，不支持纯检索模式。")

    _doc_agents[doc_uuid] = agent
    log.info(f"文档 Agent 加载完成: {doc_uuid}")
    return agent


# ── 核心检索逻辑 ──────────────────────────────────────────────────────────────

def _retrieval_only(agent: GBCRAG, query: str) -> dict:
    """
    仅执行检索流程（规划 + 图检索），跳过 LLM 答案生成。
    返回结构与 retrieval_res.json 一致，但不含答案相关字段。
    """
    context = GBCRAGContext(query=query)

    if agent.varient == "wo_plan":
        query_analysis = PlanResult(query_type="simple", original_query=query)
    else:
        query_analysis: PlanResult = agent.planner.analyze(query)

    context.plan = query_analysis

    if query_analysis.query_type == "simple":
        step = SubStep(sub_query=query, sub_number=1)
        agent._retrieve(query, step)
        context.iterations.append(step)
    elif query_analysis.query_type == "complex":
        retrieval_tasks = [
            sq for sq in query_analysis.sub_questions if sq.type == "retrieval"
        ]
        for i, task in enumerate(retrieval_tasks):
            step = SubStep(sub_query=task.question, sub_number=i + 1)
            agent._retrieve(task.question, step)
            context.iterations.append(step)
    else:
        log.warning(f"未知 query_type: {query_analysis.query_type}")

    result = context.model_dump()
    result.pop("final_answer", None)
    for iteration in result.get("iterations", []):
        iteration.pop("partial_answers", None)
        iteration.pop("generated_answer", None)
    return result


def _route_docs(
    question: str,
    title_topk: int,
    rerank_topk: int,
    max_doc: int,
) -> List[str]:
    """
    用 title_summary_vdb 路由，可选 Text Reranker 重排，返回最多 max_doc 个文档的 doc_uuid。
    """
    hits = _title_vdb.search(query_text=question, top_k=title_topk)
    if not hits:
        return []

    # 若已加载 Reranker，对召回的摘要文本做重排
    if _title_reranker is not None:
        contents = [h.get("content", "") or "" for h in hits]
        if contents:
            try:
                scores = _title_reranker.rerank(
                    query=question,
                    documents=contents,
                    instruction=TEXT_RERANKER_PROMPT,
                )
                _title_reranker.clean_cache()
                # 按 rerank 分数降序排序，取 top rerank_topk
                scored = list(zip(hits, scores))
                scored.sort(key=lambda x: x[1], reverse=True)
                hits = [h for h, _ in scored[:rerank_topk]]
                if scored:
                    lo = scored[min(rerank_topk - 1, len(scored) - 1)][1]
                    hi = scored[0][1]
                    log.info(
                        f"摘要 Reranker 重排完成，保留 top-{rerank_topk}，"
                        f"分数范围 [{lo:.4f}, {hi:.4f}]"
                    )
            except Exception as e:
                log.warning(f"摘要 Reranker 异常，回退到向量相似度排序: {e}")
        else:
            hits = hits[:rerank_topk]
    else:
        hits = hits[:rerank_topk]

    # 从重排后的 hits 中按顺序提取 doc_uuid，去重，最多 max_doc 个
    seen: dict = {}  # doc_uuid -> 首次出现的顺序/分数信息
    for hit in hits:
        file_name = hit.get("metadata", {}).get("file_name", "")
        if file_name and file_name in _doc_info and file_name not in seen:
            seen[file_name] = hit.get("distance", 1.0)
        if len(seen) >= max_doc:
            break

    matched = sorted(seen.items(), key=lambda x: x[1])  # 按 distance 升序（越小越相似）
    doc_uuids = [uuid for uuid, _ in matched]
    log.info(
        f"路由命中文档 ({len(doc_uuids)}/{max_doc}): "
        + ", ".join(f"{u}(dist={d:.4f})" for u, d in matched)
    )
    return doc_uuids


# ── FastAPI 应用 ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="BookRAG Multi-Doc API",
    description=(
        "多文档 RAG 检索服务：先通过 title_summary_vdb 做文档路由，"
        "再对命中文档执行图检索（不调用 LLM 生成答案）。"
    ),
    version="2.0.0",
)


@app.on_event("startup")
async def startup_event():
    """启动时初始化配置与路由 VDB。"""
    try:
        _init_globals()
    except Exception as e:
        log.error(f"启动初始化失败: {e}")
        raise


@app.post("/rag")
async def rag_inference(request: RAGRequest):
    """
    多文档检索接口。

    - 若 title_summary_vdb 可用：先路由文档，再对每个文档做图检索，返回多文档结果。
    - 若 title_summary_vdb 不可用（单文档回退）：对 dataset 第一个文档直接检索。
    """
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")

    # ── 多文档模式 ────────────────────────────────────────────────────────────
    if _title_vdb is not None:
        try:
            doc_uuids = _route_docs(
                question,
                request.title_topk,
                request.rerank_topk,
                request.max_doc,
            )
        except Exception as e:
            log.exception(f"文档路由异常: {e}")
            raise HTTPException(status_code=500, detail=f"文档路由失败: {str(e)}")

        if not doc_uuids:
            log.warning("路由结果为空，无文档命中。")
            return {"query": question, "mode": "failed", "results": []}

        results = []
        for doc_uuid in doc_uuids:
            try:
                agent = _get_or_load_agent(doc_uuid)
                retrieval = _retrieval_only(agent, question)
                results.append({"doc_uuid": doc_uuid, "retrieval": retrieval})
                log.info(f"文档 [{doc_uuid}] 检索完成。")
            except Exception as e:
                log.exception(f"文档 [{doc_uuid}] 检索异常: {e}")
                results.append({"doc_uuid": doc_uuid, "error": str(e)})

        return {"query": question, "mode": "multi_doc", "results": results}
    
    else:
        log.warning("title_summary_vdb 不可用")
        return {"query": question, "mode": "failed", "results": []}


@app.get("/health")
async def health():
    """健康检查，同时返回已加载文档列表。"""
    return {
        "status": "ok",
        "service": "BookRAG",
        "mode": "multi_doc" if _title_vdb is not None else "single_doc",
        "docs_in_dataset": list(_doc_info.keys()),
        "docs_loaded": list(_doc_agents.keys()),
        "title_vdb_entries": _title_vdb.collection.count() if _title_vdb else 0,
        "title_reranker_loaded": _title_reranker is not None,
    }


def main():
    uvicorn.run(
        "fastapi_server:app",
        host="0.0.0.0",
        port=6006,
        reload=False,
    )


if __name__ == "__main__":
    main()
