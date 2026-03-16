from pydantic import BaseModel, Field
from typing import Optional
import yaml


class DatasetConfig(BaseModel):
    dataset_path: str = Field(..., description="Path to the JSON dataset file.")
    working_dir: str = Field(..., description="The working directory for the project.")
    dataset_name: str

    # title_summary_vdb stage 配置
    title_vdb_dir: Optional[str] = Field(
        default=None,
        description=(
            "Directory to store the shared title-summary ChromaDB. "
            "Defaults to <working_dir>/../title_summary_vdb."
        ),
    )
    title_collection_name: str = Field(
        default="title_summary",
        description="ChromaDB collection name for the title-summary VDB.",
    )
    title_vdb_force_rebuild: bool = Field(
        default=False,
        description="If True, remove the existing title-summary VDB and rebuild from scratch.",
    )


def load_dataset_config(path: str) -> DatasetConfig:
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    data_cfg = DatasetConfig(**data)
    return data_cfg
