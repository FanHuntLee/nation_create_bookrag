"""
FastAPI 服务器：封装 RAG 推理过程，通过 POST 接口接收 question 并直接返回结果报文。
配置从 config/test_minimal.yaml 加载，doc_path 和 doc_uuid 从数据集 som-testdata.json 获取。
"""

import json
import logging
import os
import tempfile
from pathlib import Path

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# 设置项目根目录，确保导入正确
PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
import sys

sys.path.insert(0, str(PROJECT_ROOT))

from Core.configs.system_config import load_system_config, SystemConfig
from Core.configs.dataset_config import load_dataset_config
from Core.rag import create_rag_agent
from Core.utils.resource_loader import prepare_rag_dependencies

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger(__name__)

# ============ 配置路径 ============
CONFIG_PATH = PROJECT_ROOT / "config" / "test_minimal.yaml"
DATASET_CONFIG_PATH = PROJECT_ROOT / "Scripts" / "cfg" / "som-test-vl.yaml"

# ============ Pydantic 模型 ============


class RAGRequest(BaseModel):
    """POST 请求体：与 som-testdata.json 中 question 字段对应"""

    question: str = Field(..., description="待查询的问题")


# 返回完整的 retrieval_res.json 报文，使用 dict 以保持结构灵活


# ============ 全局 RAG Agent ============
_rag_agent = None
_system_config = None


def _load_config_and_agent():
    """加载配置、数据集，并初始化 RAG Agent（单例）"""
    global _rag_agent, _system_config

    if _rag_agent is not None:
        return _rag_agent, _system_config

    log.info(f"加载系统配置: {CONFIG_PATH}")
    base_config: SystemConfig = load_system_config(str(CONFIG_PATH))

    log.info(f"加载数据集配置: {DATASET_CONFIG_PATH}")
    dataset_cfg = load_dataset_config(str(DATASET_CONFIG_PATH))

    # 从数据集获取 doc_path、doc_uuid（仅一个文档，所有条目相同）
    df = pd.read_json(dataset_cfg.dataset_path)
    if df.empty:
        raise ValueError(f"数据集为空: {dataset_cfg.dataset_path}")

    first_row = df.iloc[0]
    doc_uuid = str(first_row["doc_uuid"])
    doc_path = str(first_row["doc_path"])

    # 构建当前文档的 config
    pdf_full_path = Path(doc_path)
    output_full_path = Path(dataset_cfg.working_dir) / doc_uuid

    current_config = base_config.model_copy(deep=True)
    current_config.pdf_path = str(pdf_full_path)
    current_config.save_path = str(output_full_path)

    log.info(f"知识库工作路径: pdf_path={pdf_full_path}, save_path={output_full_path}")

    # 可选：应用与 main.py 一致的资源覆盖（如 GPU、API 地址）
    # current_config.mineru.server_url = "http://localhost:30001"
    # current_config.llm.api_base = "http://localhost:8003/v1"
    if current_config.rag.strategy_config.strategy == "gbc":
        current_config.rag.strategy_config.mm_reranker_config.device = "cuda:3"

    dependencies = prepare_rag_dependencies(current_config)
    _rag_agent = create_rag_agent(
        strategy_config=current_config.rag.strategy_config,
        llm_config=current_config.llm,
        vlm_config=current_config.vlm,
        **dependencies,
    )
    _system_config = current_config
    log.info(f"RAG Agent 初始化完成，策略: {_rag_agent.name}")
    return _rag_agent, _system_config


# ============ FastAPI 应用 ============
app = FastAPI(
    title="BookRAG API",
    description="基于知识库的 RAG 推理服务，接收 question 返回完整 retrieval_res 报文",
    version="1.0.0",
)


@app.on_event("startup")
async def startup_event():
    """启动时预加载 RAG Agent"""
    try:
        _load_config_and_agent()
    except Exception as e:
        log.error(f"启动时加载 RAG Agent 失败: {e}")
        raise


@app.post("/rag")
async def rag_inference(request: RAGRequest):
    """
    接收 question 字段，执行 RAG 推理，直接返回完整的 retrieval_res.json 报文（不写入本地）。
    """
    global _rag_agent
    if _rag_agent is None:
        _rag_agent, _ = _load_config_and_agent()

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="question 不能为空")

    # 使用临时目录满足 generation() 的 query_output_dir 参数（内部会写 retrieval_res.json）
    # 推理完成后读取完整报文返回，临时目录由系统回收
    with tempfile.TemporaryDirectory(prefix="rag_query_") as tmpdir:
        query_output_dir = Path(tmpdir)
        try:
            _rag_agent.generation(
                query=question, query_output_dir=query_output_dir
            )
        except Exception as e:
            log.exception(f"RAG 推理异常: {e}")
            raise HTTPException(status_code=500, detail=f"RAG 推理失败: {str(e)}")

        retrieval_res_path = query_output_dir / "retrieval_res.json"
        if not retrieval_res_path.exists():
            raise HTTPException(
                status_code=500, detail="retrieval_res.json 未生成"
            )
        with open(retrieval_res_path, "r", encoding="utf-8") as f:
            retrieval_res = json.load(f)

    return retrieval_res


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": "BookRAG"}


def main():
    uvicorn.run(
        "fastapi_server:app",
        host="0.0.0.0",
        port=6006,
        reload=False,
    )


if __name__ == "__main__":
    main()
