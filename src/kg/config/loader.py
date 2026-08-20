"""Load and validate all configuration at startup.

Three inputs, all validated through pydantic:
  * `.env`            — secrets/hosts (DB creds, LLM endpoint + key, paths)
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
    LLMSettings,
    Ontology,
    Settings,
)

# kg-pipeline/  (src/kg/config/loader.py -> parents[3] = repo root)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _read_yaml(path: Path) -> dict:
    """Parse a YAML file to a dict; missing or empty files yield ``{}``."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _settings_yaml_path(root: Path, explicit: Path | str | None) -> Path:
    """Resolve which YAML to read: an explicit path, else settings.yaml with the
    checked-in example as fallback so a fresh checkout still runs."""
    if explicit is not None:
        return Path(explicit)
    user_yaml = root / "config" / "settings.yaml"
    return user_yaml if user_yaml.exists() else root / "config" / "settings.example.yaml"


def _build_llm_settings(llm_cfg: dict) -> LLMSettings:
    """Assemble LLMSettings from env + the YAML ``llm:`` block.

    Env wins where both are set. Every provider — OpenRouter, vLLM, OpenAI,
    Ollama, ... — is configured identically; the provider name only selects
    preset defaults (filled by ``kg.llm.factory``), never a code path.
    """
    provider = os.getenv("LLM_PROVIDER") or llm_cfg.get("provider") or "openrouter"
    provider = provider.strip().lower()

    allowed_env = [
        p.strip() for p in (os.getenv("LLM_ALLOWED_PROVIDERS", "") or "").split(",") if p.strip()
    ]
    allowed = allowed_env or [
        str(p).strip() for p in (llm_cfg.get("allowed_providers") or []) if str(p).strip()
    ]

    headers = dict(llm_cfg.get("extra_headers") or {})
    referer = os.getenv("LLM_HTTP_REFERER")
    if referer:
        headers["HTTP-Referer"] = referer

    return LLMSettings(
        provider=provider,
        model=os.getenv("LLM_MODEL") or llm_cfg.get("model") or "",
        base_url=os.getenv("LLM_BASE_URL") or llm_cfg.get("base_url") or "",
        api_key=os.getenv("LLM_API_KEY") or llm_cfg.get("api_key") or "",
        timeout=float(os.getenv("LLM_TIMEOUT") or llm_cfg.get("timeout") or 120.0),
        max_retries=int(os.getenv("LLM_MAX_RETRIES") or llm_cfg.get("max_retries") or 2),
        concurrency=int(os.getenv("LLM_CONCURRENCY") or llm_cfg.get("concurrency") or 2),
        structured_mode=os.getenv("LLM_STRUCTURED_MODE")
        or llm_cfg.get("structured_mode")
        or "auto",
        allowed_providers=allowed,
        max_tokens=(
            int(os.getenv("LLM_MAX_TOKENS"))
            if os.getenv("LLM_MAX_TOKENS")
            else llm_cfg.get("max_tokens")
        ),
        extra_headers=headers,
    )


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
    llm = _build_llm_settings(llm_cfg)

    ontology_raw = os.getenv("ONTOLOGY_PATH", "config/ontologies/generic.yaml")
    chunker = os.getenv("CHUNKER") or ingest_cfg.get("chunker") or "fixed"

    settings = Settings(
        db=db,
        llm=llm,
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
