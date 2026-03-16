"""
title-summary 向量库检索测试脚本（仅检索，不构建）。
构建向量库请使用：
    python main.py -c <system_cfg.yaml> -d TL3588_data_and_output/TL3588.yaml \
        index --stage title_summary_vdb

用法：
    cd /root/autodl-fs/bookrag/BookRAG
    python test_title_summary_vdb.py
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

from Core.configs.dataset_config import load_dataset_config
from Core.configs.embedding_config import EmbeddingConfig
from Core.provider.vdb import VectorStore
from Core.provider.embedding import TextEmbeddingProvider

# ── 配置区域 ──────────────────────────────────────────────────────────────────

DATASET_CONFIG_PATH = "TL3588_data_and_output/TL3588.yaml"

EMBEDDING_CFG = EmbeddingConfig(
    backend="local",
    model_name="/root/autodl-fs/models/Qwen3-Embedding-0.6B",
    device="cuda:0",
    max_length=30000,
)

TEST_QUERIES = [
    "RK3588 电源设计注意事项",
    "LOGO 启动画面替换方法",
    "SOM核心板 硬件接口说明",
    "TL3588-EVM 评估板 IO 电平",
    "DDR 内存布局设计规范",
    "USB 接口电路设计",
    "PCIe 信号完整性",
]

TOP_K = 5

# ─────────────────────────────────────────────────────────────────────────────


def print_results(query: str, results: list):
    print(f"\n{'─' * 70}")
    print(f"Query: 「{query}」")
    print(f"{'─' * 70}")
    if not results:
        print("  (no results)")
        return
    for i, r in enumerate(results, 1):
        meta = r["metadata"]
        similarity = 1 - r["distance"]
        file_name = meta.get("file_name", "unknown")
        title = meta.get("title_content", "")[:40]
        summary = r["content"][:120]
        print(f"  [{i}] 相似度={similarity:.4f}  文档=《{file_name}》")
        print(f"       标题: {title}")
        print(f"       摘要: {summary}")


def main():
    dataset_cfg = load_dataset_config(DATASET_CONFIG_PATH)

    vdb_dir = dataset_cfg.title_vdb_dir
    collection_name = dataset_cfg.title_collection_name

    log.info(f"Loading VDB from: {vdb_dir}  (collection: {collection_name})")

    embedder = TextEmbeddingProvider(
        model_name=EMBEDDING_CFG.model_name,
        device=EMBEDDING_CFG.device,
        backend=EMBEDDING_CFG.backend,
        api_base=EMBEDDING_CFG.api_base,
        max_length=EMBEDDING_CFG.max_length,
    )
    vdb = VectorStore(
        embedding_model=embedder,
        db_path=vdb_dir,
        collection_name=collection_name,
    )

    total = vdb.collection.count()
    log.info(f"Collection entries: {total}")
    if total == 0:
        log.error("Collection is empty. Please build the VDB first:")
        log.error(
            "  python main.py -c <system_cfg.yaml> "
            "-d TL3588_data_and_output/TL3588.yaml index --stage title_summary_vdb"
        )
        sys.exit(1)

    log.info(f"Running {len(TEST_QUERIES)} queries (top_k={TOP_K})...")
    for query in TEST_QUERIES:
        results = vdb.search(query_text=query, top_k=TOP_K)
        print_results(query, results)

    print(f"\n{'═' * 70}")
    embedder.close()


if __name__ == "__main__":
    main()
