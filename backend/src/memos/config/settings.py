"""Application configuration for MemOS.

Uses ``pydantic-settings`` so configuration may come from environment
variables (prefixed ``MEMOS_``), a ``.env`` file, or defaults. No hardcoded
paths or magic values: everything configurable lives here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration object for all MemOS subsystems."""

    model_config = SettingsConfigDict(
        env_prefix="MEMOS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- runtime ---------------------------------------------------------
    app_name: str = "MemOS"
    version: str = "0.1.0"
    debug: bool = False

    # ---- storage ---------------------------------------------------------
    storage_backend: str = "sqlite"  # sqlite (implemented) | postgres (planned)
    database_path: str = "data/memos_metadata.db"  # SQLite file or DSN for postgres

    # ---- vector / embedding ---------------------------------------------
    embedding_dimension: int = 256
    embedding_backend: str = "hash"  # hash (deterministic local) | configured provider
    vector_store_backend: str = "sqlite"  # sqlite (persistent) | memory (dev)
    vector_db_path: str = "data/memos_vectors.db"
    graph_store_backend: str = "sqlite"  # sqlite (persistent) | memory (dev)
    graph_db_path: str = "data/memos_graph.db"

    # ---- retrieval -------------------------------------------------------
    default_top_k: int = 10
    rank_alpha: float = 0.40   # semantic similarity weight
    rank_beta: float = 0.30    # importance weight
    rank_gamma: float = 0.15   # confidence weight
    rank_delta: float = 0.10   # recency weight
    rank_epsilon: float = 0.05 # graph connectivity weight

    # ---- importance engine ------------------------------------------------
    importance_epochs: int = 10

    # ---- permissions ------------------------------------------------------
    default_permission: str = "private"

    # ---- logging ----------------------------------------------------------
    log_level: str = "INFO"

    # ---- config file worker ------------------------------------------------
    data_dir: Path = Field(default_factory=lambda: Path("data"))


settings = Settings()