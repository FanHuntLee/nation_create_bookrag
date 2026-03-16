import json
import os
import logging
import time
import pandas as pd
from typing import List

from Core.configs.vdb_config import VDBConfig

log = logging.getLogger(__name__)

from Core.Index.GBCIndex import GBC
from Core.configs.dataset_config import DatasetConfig
from Core.configs.system_config import SystemConfig
from Core.pipelines.doc_tree_builder import build_tree_from_pdf_or_markdown
from Core.pipelines.kg_builder import build_knowledge_graph
from Core.pipelines.vdb_index import (
    build_other_vdb_index,
    build_vdb_index,
    build_title_summary_vdb_from_json,
    compute_mm_embedding,
    compute_mm_embedding_question,
)
from Core.provider.TokenTracker import TokenTracker
from Core.utils.file_utils import save_indexing_stats


def construct_GBC_index(cfg: SystemConfig, tree_only: bool = False):
    """
    Construct the GBC index from the document tree and knowledge graph.

    :param cfg: Configuration object containing settings for the index construction.
    :return: A tuple containing the DocumentTree and Graph objects.
    """
    log.info("Starting GBC index construction...")

    token_tracker = TokenTracker.get_instance()
    token_tracker.reset()

    # This dictionary will hold all stats for the CURRENT run
    current_run_stats = {}

    # --- Measure Tree Building ---
    tree_start_time = time.time()
    tree_index = build_tree_from_pdf_or_markdown(cfg)
    tree_duration = time.time() - tree_start_time
    log.info(f"Document tree constructed in {tree_duration:.2f} seconds.")
    current_run_stats["build_tree_time"] = round(tree_duration, 2)

    if tree_only:
        log.info("Only build tree index. Finished.")
        # Add final token usage to our stats dictionary
        current_run_stats["token_stage_history"] = token_tracker.stage_history

        # Save all collected stats and exit
        save_indexing_stats(save_path=cfg.save_path, new_stats=current_run_stats)
        return tree_index

    # --- Measure Knowledge Graph Building ---
    kg_start_time = time.time()
    graph_index = build_knowledge_graph(tree_index, cfg)

    gbc_index = GBC.build_gbc_index(graph_index, cfg, tree_index)

    kg_duration = time.time() - kg_start_time
    log.info(f"Knowledge graph constructed and saved in {kg_duration:.2f} seconds.")
    current_run_stats["build_kg_time"] = round(kg_duration, 2)

    # --- Finalize and Save All Stats for the Full Run ---
    log.info("Full GBC index construction finished. Saving final stats...")
    current_run_stats["token_stage_history"] = token_tracker.stage_history

    save_indexing_stats(save_path=cfg.save_path, new_stats=current_run_stats)

    return gbc_index

def rebuild_graph_vdb(cfg: SystemConfig):
    gbc_index = GBC.load_gbc_index(cfg)
    gbc_index.rebuild_vdb()
    log.info("Rebuilt graph VDB successfully.")


def construct_vdb(cfg: SystemConfig):
    token_tracker = TokenTracker.get_instance()
    token_tracker.reset()

    log.info("Starting vector database construction...")

    if cfg.index_type in ["vanilla", "bm25", "raptor"]:
        log.info(f"Index type is {cfg.index_type}. Start building other vdb index...")
        build_other_vdb_index(cfg)
        return

    current_run_stats = {}

    tree_start_time = time.time()
    tree_index = build_tree_from_pdf_or_markdown(cfg)
    tree_duration = time.time() - tree_start_time
    log.info(f"Document tree constructed in {tree_duration:.2f} seconds.")
    current_run_stats["build_tree_time"] = round(tree_duration, 2)

    log.info("Document tree constructed successfully for vector database.")

    current_run_stats["token_stage_history"] = token_tracker.stage_history

    # Save all collected stats and exit
    save_indexing_stats(save_path=cfg.save_path, new_stats=current_run_stats)

    vdb_cfg: VDBConfig = cfg.vdb
    if cfg.save_path not in vdb_cfg.vdb_dir_name:
        vdb_cfg.vdb_dir_name = os.path.join(cfg.save_path, vdb_cfg.vdb_dir_name)
    log.info(f"Vector database path set to: {vdb_cfg.vdb_dir_name}")

    # if exist the dir, remove and rebuild vdb
    if os.path.exists(vdb_cfg.vdb_dir_name) and not vdb_cfg.force_rebuild:
        log.info(f"Vector database path already exists: {vdb_cfg.vdb_dir_name}. Skip")
        return

    if vdb_cfg.force_rebuild and os.path.exists(vdb_cfg.vdb_dir_name):
        log.info(
            f"Vector database path already exists: {vdb_cfg.vdb_dir_name}. Remove and rebuild"
        )
        import shutil

        shutil.rmtree(vdb_cfg.vdb_dir_name)

    os.makedirs(os.path.dirname(vdb_cfg.vdb_dir_name), exist_ok=True)

    vbd_start_time = time.time()
    build_vdb_index(tree_index, vdb_cfg)
    vdb_duration = time.time() - vbd_start_time
    log.info(f"Vector database constructed in {vdb_duration:.2f} seconds.")

    current_run_stats["build_vdb_time"] = round(vdb_duration, 2)

    # Save all collected stats and exit
    save_indexing_stats(save_path=cfg.save_path, new_stats=current_run_stats)


def compute_mm_reranker(cfg: SystemConfig, group: pd.DataFrame):
    tree_index = build_tree_from_pdf_or_markdown(cfg)
    compute_mm_embedding(cfg, tree_index)
    compute_mm_embedding_question(cfg, group)


def build_multi_doc_title_summary_vdb(
    dataset_cfg: DatasetConfig,
    system_cfg: SystemConfig,
):
    """
    根据 DatasetConfig 收集所有文档的 tree.json，对 NodeType.TITLE 节点的 summary
    进行向量化，构建统一的 ChromaDB 持久化向量库。

    路径规则：working_dir/<doc_uuid>/tree.json
    VDB 存储路径优先取 dataset_cfg.title_vdb_dir，
    未配置时默认为 <working_dir>/../title_summary_vdb。

    通常在所有文档树构建完毕后调用，用于支持跨文档的文档级粗检索。

    Args:
        dataset_cfg: DatasetConfig 实例，提供 dataset_path / working_dir 及 VDB 相关配置
        system_cfg:  SystemConfig 实例，提供 vdb.embedding_config
    """
    with open(dataset_cfg.dataset_path, "r", encoding="utf-8") as f:
        testdata = json.load(f)

    doc_uuids = list(dict.fromkeys(
        item["doc_uuid"]
        for item in testdata
        if item.get("doc_uuid", "").strip()
    ))
    log.info(f"Found {len(doc_uuids)} unique doc_uuids: {doc_uuids}")

    tree_json_paths = []
    for uid in doc_uuids:
        path = os.path.join(dataset_cfg.working_dir, uid, "tree.json")
        if os.path.isfile(path):
            tree_json_paths.append(path)
            log.info(f"  Found tree.json: {path}")
        else:
            log.warning(f"  tree.json not found, skipped: {path}")

    if not tree_json_paths:
        log.error("No valid tree.json files found. Skipping title-summary VDB construction.")
        return

    vdb_dir = dataset_cfg.title_vdb_dir or os.path.join(
        os.path.dirname(dataset_cfg.working_dir.rstrip("/")),
        "title_summary_vdb",
    )

    log.info(f"Building multi-doc title-summary VDB with {len(tree_json_paths)} document(s)...")
    build_title_summary_vdb_from_json(
        tree_json_paths=tree_json_paths,
        vdb_dir=vdb_dir,
        collection_name=dataset_cfg.title_collection_name,
        embedding_cfg=system_cfg.graph.embedding_config,
        force_rebuild=dataset_cfg.title_vdb_force_rebuild,
    )
    log.info(f"Multi-doc title-summary VDB saved to: {vdb_dir}")


if __name__ == "__main__":
    print("test")

    # parser = argparse.ArgumentParser(description="Extract text content from PDF files.")
    # parser.add_argument(
    #     "--config_path",
    #     type=str,
    #     default="/home/wangshu/multimodal/GBC-RAG/config/gbc.yaml",
    #     help="Path to the configuration file.",
    # )

    # args = parser.parse_args()

    # cfg = load_system_config(args.config_path)

    # if not os.path.exists(cfg.save_path):
    #     os.makedirs(cfg.save_path)
    #     log.info(f"Created directory: {cfg.save_path}")
    # else:
    #     log.info(f"Directory already exists: {cfg.save_path}")

    # construct_vdb(cfg)

    # gbc_index = construct_GBC_index(cfg)
    # log.info("GBC index construction completed successfully.")
