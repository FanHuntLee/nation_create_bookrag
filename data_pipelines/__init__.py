"""
pipelines —— QA 数据集构建流水线包

快速使用：
    from data_pipelines.build_qa_dataset import run_pipeline

    samples = run_pipeline(
        tree_json="/path/to/tree.json",
        doc_uuid="som-001",
        output="/path/to/qa_dataset.json",
        num_samples=50,
        llm_base_url="http://localhost:8003/v1",
        llm_model="Qwen/Qwen3-8B-AWQ",
    )
"""

from data_pipelines.build_qa_dataset import run_pipeline, run_pipeline_from_config, PipelineConfig
from data_pipelines.chunk_sampler import ChunkSampler, RatioConfig, load_tree_json
from data_pipelines.qa_generator import QAGenerator

__all__ = [
    "run_pipeline",
    "run_pipeline_from_config",
    "PipelineConfig",
    "ChunkSampler",
    "RatioConfig",
    "load_tree_json",
    "QAGenerator",
]
