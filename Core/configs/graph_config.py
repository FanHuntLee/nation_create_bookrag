from dataclasses import dataclass, field

from Core.configs.embedding_config import EmbeddingConfig
from Core.configs.rerank_config import RerankerConfig


@dataclass
class GraphConfig:
    # KG extraction
    extractor_type: str = "llm"  # Options: "llm", "local"
    local_model_name: str = "en_core_web_sm"
    image_description_force: bool = False
    max_gleaning: int = 0

    # KG refinement
    refine_type: str = "advanced"  # Options: "basic", "advanced"
    
    # Remote KG service (when True, delegate to external API)
    use_remote_kg_service: bool = False
    kg_service_url: str = "http://localhost:8080"

    embedding_config: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    reranker_config: RerankerConfig = field(default_factory=RerankerConfig)
