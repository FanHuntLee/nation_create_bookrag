"""
QA 数据集构建流水线 —— 主入口

用法示例：
  # 命令行
  python -m data_pipelines.build_qa_dataset \\
      --tree_json /path/to/tree.json \\
      --doc_uuid som-001 \\
      --output /path/to/qa_dataset.json \\
      --num_samples 50 \\
      --llm_base_url http://localhost:8003/v1 \\
      --llm_model Qwen/Qwen3-8B-AWQ

  # 使用配置文件
  python -m data_pipelines.build_qa_dataset --config /path/to/pipeline_config.yaml

  # Python 函数调用
  from data_pipelines.build_qa_dataset import run_pipeline
  run_pipeline(tree_json="...", doc_uuid="som-001", output="...", num_samples=50)
"""

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import yaml

# 确保从 BookRAG 根目录可以 import Core
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Core.configs.llm_config import LLMConfig
from Core.provider.llm import OpenAIController
from data_pipelines.chunk_sampler import ChunkSampler, RatioConfig, load_tree_json
from data_pipelines.qa_generator import QAGenerator, deduplicate_questions, print_distribution_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 配置数据类
# ──────────────────────────────────────────────

class PipelineConfig:
    """流水线全局配置（从 YAML 或 CLI 参数加载）。"""

    def __init__(
        self,
        tree_json: str,
        doc_uuid: str,
        output: str,
        num_samples: int = 50,
        grouping_method: str = "tree",
        llm_model: str = "Qwen/Qwen3-8B-AWQ",
        llm_base_url: str = "http://localhost:8003/v1",
        llm_api_key: str = "openai",
        llm_temperature: float = 0.7,
        llm_max_tokens: int = 1024,
        llm_max_workers: int = 4,
        seed: int = 42,
        ratio: Optional[Dict] = None,
        dedup: bool = True,
    ):
        self.tree_json = tree_json
        self.doc_uuid = doc_uuid
        self.output = output
        self.num_samples = num_samples
        self.grouping_method = grouping_method
        self.llm_model = llm_model
        self.llm_base_url = llm_base_url
        self.llm_api_key = llm_api_key
        self.llm_temperature = llm_temperature
        self.llm_max_tokens = llm_max_tokens
        self.llm_max_workers = llm_max_workers
        self.seed = seed
        self.ratio_dict = ratio or {}
        self.dedup = dedup

    @classmethod
    def from_yaml(cls, yaml_path: str) -> "PipelineConfig":
        with open(yaml_path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)

        llm_d = d.get("llm", {})
        return cls(
            tree_json=d["tree_json"],
            doc_uuid=d["doc_uuid"],
            output=d["output"],
            num_samples=d.get("num_samples", 50),
            grouping_method=d.get("grouping_method", "tree"),
            llm_model=llm_d.get("model_name", "Qwen/Qwen3-8B-AWQ"),
            llm_base_url=llm_d.get("api_base", "http://localhost:8003/v1"),
            llm_api_key=llm_d.get("api_key", "openai"),
            llm_temperature=llm_d.get("temperature", 0.7),
            llm_max_tokens=llm_d.get("max_tokens", 1024),
            llm_max_workers=llm_d.get("max_workers", 4),
            seed=d.get("seed", 42),
            ratio=d.get("ratio"),
            dedup=d.get("dedup", True),
        )


# ──────────────────────────────────────────────
# 核心流水线函数
# ──────────────────────────────────────────────

def run_pipeline(
    tree_json: str,
    doc_uuid: str,
    output: str,
    num_samples: int = 50,
    grouping_method: str = "tree",
    llm_model: str = "Qwen/Qwen3-8B-AWQ",
    llm_base_url: str = "http://localhost:8003/v1",
    llm_api_key: str = "openai",
    llm_temperature: float = 0.7,
    llm_max_tokens: int = 1024,
    llm_max_workers: int = 4,
    seed: int = 42,
    ratio: Optional[Dict] = None,
    dedup: bool = True,
) -> List[Dict[str, Any]]:
    """
    完整运行 QA 数据集构建流水线。

    Args:
        tree_json: tree.json 文件路径
        doc_uuid: 文档唯一标识（如 "som-001"）
        output: 输出的 QA 数据集 JSON 文件路径
        num_samples: 目标样本数量
        grouping_method: 多 chunk 分组策略（"tree" 或 "llm_semantic"）
        llm_model: LLM 模型名称
        llm_base_url: LLM API 地址
        llm_api_key: LLM API Key
        llm_temperature: 生成温度
        llm_max_tokens: 最大输出 token 数
        llm_max_workers: 并发 worker 数
        seed: 随机种子
        ratio: 各维度比例配置字典（见 RatioConfig.from_dict）
        dedup: 是否对最终结果去重

    Returns:
        生成的 QA 样本列表
    """
    log.info("========== QA 数据集构建流水线启动 ==========")
    log.info("tree_json=%s, doc_uuid=%s, num_samples=%d", tree_json, doc_uuid, num_samples)
    log.info("grouping_method=%s, llm=%s @ %s", grouping_method, llm_model, llm_base_url)

    # Step 1: 加载 tree.json
    log.info("[Step 1] 加载 tree.json ...")
    nodes, doc_path = load_tree_json(tree_json)
    doc_name = os.path.basename(doc_path) if doc_path else "未知文档"
    id2node = {n["index_id"]: n for n in nodes}

    # Step 2: 初始化 LLM
    log.info("[Step 2] 初始化 LLM 控制器 ...")
    llm_cfg = LLMConfig(
        model_name=llm_model,
        api_base=llm_base_url,
        api_key=llm_api_key,
        temperature=llm_temperature,
        max_tokens=llm_max_tokens,
        max_workers=llm_max_workers,
        backend="openai",
    )
    llm_controller = OpenAIController(llm_config=llm_cfg)

    # Step 3: Chunk 采样
    log.info("[Step 3] 执行 Chunk 采样 ...")
    ratio_cfg = RatioConfig.from_dict(ratio or {})
    sampler = ChunkSampler(nodes, ratio=ratio_cfg, seed=seed)

    llm_for_grouping = llm_controller if grouping_method == "llm_semantic" else None
    groups = sampler.sample(
        num_samples=num_samples,
        grouping_method=grouping_method,
        llm_controller=llm_for_grouping,
    )
    log.info("采样得到 %d 个 chunk 分组", len(groups))

    # Step 4: LLM 问答生成
    log.info("[Step 4] 开始 LLM 问答生成（并发 workers=%d）...", llm_max_workers)
    generator = QAGenerator(
        llm_controller=llm_controller,
        doc_uuid=doc_uuid,
        doc_path=doc_path,
        doc_name=doc_name,
        id2node=id2node,
        max_workers=llm_max_workers,
    )
    samples = generator.generate(groups)

    # Step 5: 去重
    if dedup and len(samples) > 1:
        log.info("[Step 5] 执行问题去重 ...")
        samples = deduplicate_questions(samples)

    # Step 6: 保存结果
    log.info("[Step 6] 保存结果到 %s ...", output)
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(samples, f, ensure_ascii=False, indent=2)

    log.info("已保存 %d 条 QA 样本到 %s", len(samples), output)

    # Step 7: 输出分布报告
    print_distribution_report(samples)

    log.info("========== 流水线完成 ==========")
    return samples


def run_pipeline_from_config(config: PipelineConfig) -> List[Dict[str, Any]]:
    """从 PipelineConfig 对象运行流水线。"""
    return run_pipeline(
        tree_json=config.tree_json,
        doc_uuid=config.doc_uuid,
        output=config.output,
        num_samples=config.num_samples,
        grouping_method=config.grouping_method,
        llm_model=config.llm_model,
        llm_base_url=config.llm_base_url,
        llm_api_key=config.llm_api_key,
        llm_temperature=config.llm_temperature,
        llm_max_tokens=config.llm_max_tokens,
        llm_max_workers=config.llm_max_workers,
        seed=config.seed,
        ratio=config.ratio_dict,
        dedup=config.dedup,
    )


# ──────────────────────────────────────────────
# CLI 入口
# ──────────────────────────────────────────────

def _parse_args():
    parser = argparse.ArgumentParser(
        description="从 tree.json 自动构建 QA 评测数据集",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="YAML 配置文件路径（指定后其余参数均可省略）",
    )
    parser.add_argument("--tree_json", type=str, help="tree.json 文件路径")
    parser.add_argument("--doc_uuid", type=str, default="unknown", help="文档 UUID（如 som-001）")
    parser.add_argument("--output", type=str, help="输出的 QA 数据集 JSON 路径")
    parser.add_argument("--num_samples", type=int, default=50, help="目标样本数量")
    parser.add_argument(
        "--grouping_method",
        type=str,
        default="tree",
        choices=["tree", "llm_semantic"],
        help="多 chunk 分组策略",
    )
    parser.add_argument(
        "--llm_model",
        type=str,
        default="Qwen/Qwen3-8B-AWQ",
        help="LLM 模型名称",
    )
    parser.add_argument(
        "--llm_base_url",
        type=str,
        default="http://localhost:8003/v1",
        help="LLM API 地址",
    )
    parser.add_argument("--llm_api_key", type=str, default="openai")
    parser.add_argument("--llm_temperature", type=float, default=0.7)
    parser.add_argument("--llm_max_tokens", type=int, default=1024)
    parser.add_argument("--llm_max_workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--no_dedup", action="store_true", help="禁用问题去重")
    return parser.parse_args()


def main():
    args = _parse_args()

    if args.config:
        config = PipelineConfig.from_yaml(args.config)
    else:
        if not args.tree_json or not args.output:
            print("错误：必须指定 --tree_json 和 --output，或使用 --config 指定配置文件")
            sys.exit(1)
        config = PipelineConfig(
            tree_json=args.tree_json,
            doc_uuid=args.doc_uuid,
            output=args.output,
            num_samples=args.num_samples,
            grouping_method=args.grouping_method,
            llm_model=args.llm_model,
            llm_base_url=args.llm_base_url,
            llm_api_key=args.llm_api_key,
            llm_temperature=args.llm_temperature,
            llm_max_tokens=args.llm_max_tokens,
            llm_max_workers=args.llm_max_workers,
            seed=args.seed,
            dedup=not args.no_dedup,
        )

    run_pipeline_from_config(config)


if __name__ == "__main__":
    main()
