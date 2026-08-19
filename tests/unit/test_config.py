"""Config + ontology loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from kg.config.loader import load_ontology, load_settings
from kg.config.models import Ontology


def test_load_generic_ontology(generic_ontology_path: Path) -> None:
    onto = load_ontology(generic_ontology_path)
    assert onto.name == "generic"
    assert "Entity" in onto.node_labels()
    assert "RELATED_TO" in onto.relationship_labels()
    assert ("RELATED_TO", "Entity", "Entity") in onto.allowed_rel_pairs()


def test_load_constitution_ontology(constitution_ontology_path: Path) -> None:
    onto = load_ontology(constitution_ontology_path)
    assert {"Part", "Article", "Amendment", "Institution"} == onto.node_labels()
    assert len(onto.relationship_types) == 4


def test_bad_ontology_rel_unknown_target() -> None:
    with pytest.raises(ValidationError) as exc:
        Ontology.model_validate(
            {
                "name": "bad",
                "node_types": [{"label": "A"}],
                "relationship_types": [{"label": "R", "source": "A", "target": "Z"}],
            }
        )
    assert "unknown target" in str(exc.value).lower()


def test_bad_ontology_duplicate_node_labels() -> None:
    with pytest.raises(ValidationError) as exc:
        Ontology.model_validate({"name": "bad", "node_types": [{"label": "A"}, {"label": "A"}]})
    assert "duplicate" in str(exc.value).lower()


def test_bad_ontology_no_node_types() -> None:
    with pytest.raises(ValidationError):
        Ontology.model_validate({"name": "bad", "node_types": []})


def test_load_settings_from_env(tmp_path: Path, project_root: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "POSTGRES_USER=u\nPOSTGRES_PASSWORD=p\nPOSTGRES_DB=d\n"
        "LLM_PROVIDER=openrouter\nLLM_MODEL=vendor/model\nLLM_API_KEY=sk-test\n"
        "ONTOLOGY_PATH=config/ontologies/constitution.yaml\n"
    )
    settings = load_settings(env_path=env, project_root=project_root)
    assert settings.db.user == "u"
    assert settings.llm.provider == "openrouter"
    assert settings.llm.model == "vendor/model"
    assert settings.llm.api_key == "sk-test"
    assert settings.ontology_path.name == "constitution.yaml"
    assert settings.ontology_path.exists()


def test_ollama_is_just_another_endpoint(tmp_path: Path, project_root: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "LLM_PROVIDER=ollama\nLLM_MODEL=qwen3:14b\nLLM_BASE_URL=http://localhost:11434/v1\n"
    )
    settings = load_settings(env_path=env, project_root=project_root)
    assert settings.llm.provider == "ollama"
    assert settings.llm.base_url == "http://localhost:11434/v1"
    assert settings.llm.model == "qwen3:14b"


def test_llm_base_url_requires_v1(tmp_path: Path) -> None:
    from pydantic import ValidationError

    from kg.config.models import LLMSettings

    with pytest.raises(ValidationError) as exc:
        LLMSettings(base_url="http://localhost:8000")
    assert "/v1" in str(exc.value)


def test_llm_settings_redacted_hides_key() -> None:
    from kg.config.models import LLMSettings

    s = LLMSettings(api_key="sk-secret")
    assert s.redacted()["api_key"] == "***"
    assert "sk-secret" not in str(s.redacted())


def test_yaml_is_valid(generic_ontology_path: Path, constitution_ontology_path: Path) -> None:
    for p in (generic_ontology_path, constitution_ontology_path):
        assert isinstance(yaml.safe_load(p.read_text()), dict)


def test_default_chunker_is_fixed(
    tmp_path: Path, project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pin the shipped default: nothing set in env or YAML -> fixed.
    monkeypatch.delenv("CHUNKER", raising=False)
    env = tmp_path / ".env"
    env.write_text("POSTGRES_USER=u\nPOSTGRES_PASSWORD=p\nPOSTGRES_DB=d\n")
    settings = load_settings(
        env_path=env,
        project_root=project_root,
        settings_path=project_root / "config" / "settings.example.yaml",
    )
    assert settings.chunker == "fixed"
    assert settings.chunk_size == 1200
    assert settings.chunk_overlap == 200
