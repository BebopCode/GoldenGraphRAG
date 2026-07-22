"""Load and validate all configuration at startup.

Three inputs, all validated through pydantic:
  * `.env`            — secrets/hosts (DB creds, Ollama host, model, paths)
  * `settings.yaml`   — tuning knobs (chunk sizes, batch sizes, temperature)
  * `ontology.yaml`   — node/relationship types (the modular domain definition)

Env values win where they overlap with the YAML. A missing/invalid value raises
here, at startup — never mid-run.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from kg.config.models import (
    DatabaseSettings,
    OllamaSettings,
    Ontology,
    Settings,
)

# kg-pipeline/  (src/kg/config/loader.py -> parents[3] = repo root)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _settings_yaml_path(root: Path, explicit: Path | str | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    user_yaml = root / "config" / "settings.yaml"
    return user_yaml if user_yaml.exists() else root / "config" / "settings.example.yaml"


def load_settings(
    *,
    env_path: Path | str | None = None,
    settings_path: Path | str | None = None,
    project_root: Path | str | None = None,
) -> Settings:
    """Build a validated :class:`Settings` from .env + settings.yaml.

    Paths default to the project layout, but can be overridden (for tests).
    """
    root = Path(project_root) if project_root else PROJECT_ROOT

    env_file = Path(env_path) if env_path else root / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)
    # else: fall back to whatever is already in os.environ (CI, manual export)

    cfg = _read_yaml(_settings_yaml_path(root, settings_path))
    llm_cfg = cfg.get("llm", {}) or {}
    ingest_cfg = cfg.get("ingest", {}) or {}
    extract_cfg = cfg.get("extract", {}) or {}
    fusion_cfg = cfg.get("fusion", {}) or {}
    fixed_cfg = ingest_cfg.get("fixed", {}) or {}

    db = DatabaseSettings(
        user=os.getenv("POSTGRES_USER", ""),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        dbname=os.getenv("POSTGRES_DB", ""),
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        graph_name=os.getenv("AGE_GRAPH_NAME", "kg_graph"),
    )
    ollama = OllamaSettings(
        host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        model=os.getenv("OLLAMA_MODEL", "llama3.1"),
        timeout=float(os.getenv("OLLAMA_TIMEOUT", "120")),
    )

    ontology_raw = os.getenv("ONTOLOGY_PATH", "config/ontologies/generic.yaml")
    chunker = os.getenv("CHUNKER") or ingest_cfg.get("chunker") or "structural"

    settings = Settings(
        db=db,
        ollama=ollama,
        ontology_path=Path(ontology_raw),
        chunker=chunker,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        temperature=float(llm_cfg.get("temperature", 0.0)),
        json_mode=bool(llm_cfg.get("json_mode", True)),
        chunk_size=int(fixed_cfg.get("chunk_size", 1200)),
        chunk_overlap=int(fixed_cfg.get("chunk_overlap", 200)),
        extract_batch_size=int(extract_cfg.get("batch_size", 8)),
        max_retries=int(extract_cfg.get("max_retries", 1)),
        use_embeddings_fusion=bool(fusion_cfg.get("use_embeddings", False)),
    )

    # Resolve ontology path relative to the project root for downstream use.
    if not settings.ontology_path.is_absolute():
        settings = settings.model_copy(update={"ontology_path": root / settings.ontology_path})

    try:
        return settings
    except ValidationError:
        raise  # model_validate already raised above; kept for clarity


def load_ontology(
    path: Path | str | None = None,
    *,
    settings: Settings | None = None,
    project_root: Path | str | None = None,
) -> Ontology:
    """Load and validate an ontology YAML into an :class:`Ontology`."""
    root = Path(project_root) if project_root else PROJECT_ROOT
    if path is None:
        if settings is None:
            settings = load_settings(project_root=root)
        path = settings.ontology_path
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    data = _read_yaml(p)
    return Ontology.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings access for app-wide use (CLI, pipeline)."""
    return load_settings()
