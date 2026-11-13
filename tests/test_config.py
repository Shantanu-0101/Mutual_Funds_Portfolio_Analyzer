"""Tests for src/config.py: strict loading, path resolution, env overrides, secrets kept out."""

from pathlib import Path

import pytest
import yaml

from src.config import DEFAULT_CONFIG, ConfigError, load_settings

NO_ENV = Path("does-not-exist.env")


def _write_config(tmp_path: Path, mutate=None) -> Path:
    raw = yaml.safe_load(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    if mutate:
        mutate(raw)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path


def test_real_config_loads():
    s = load_settings(env_file=NO_ENV, environ={})
    assert s.llm.provider == "groq" and s.llm.model == "openai/gpt-oss-120b"
    assert s.retrieval.top_k == 5
    assert s.data.eval_months == ("2026-09-30",)
    assert s.paths.raw.is_absolute() and s.paths.raw.name == "raw"
    assert set(s.chunking) == {"fixed_size", "header_window", "scheme_level", "section_aware", "hierarchical"}


def test_relative_paths_resolve_against_config_folder_absolute_kept(tmp_path):
    outside = tmp_path / "outside_onedrive" / "chroma"

    def mutate(raw):
        raw["paths"]["chroma"] = str(outside)

    s = load_settings(_write_config(tmp_path, mutate), env_file=NO_ENV, environ={})
    assert s.paths.chroma == outside
    assert s.paths.raw == (tmp_path / "data" / "raw").resolve()


def test_llm_provider_env_override():
    s = load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "Mock"})
    assert s.llm.provider == "mock"


def test_invalid_provider_rejected():
    with pytest.raises(ConfigError, match="llm.provider"):
        load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "openai"})


def test_missing_key_rejected(tmp_path):
    path = _write_config(tmp_path, lambda raw: raw["retrieval"].pop("top_k"))
    with pytest.raises(ConfigError, match="missing keys"):
        load_settings(path, env_file=NO_ENV, environ={})


def test_unknown_key_rejected(tmp_path):
    path = _write_config(tmp_path, lambda raw: raw["retrieval"].update(topk=3))
    with pytest.raises(ConfigError, match="unknown keys"):
        load_settings(path, env_file=NO_ENV, environ={})


def test_bad_eval_month_rejected(tmp_path):
    path = _write_config(tmp_path, lambda raw: raw["data"].update(eval_months=["Sep 2026"]))
    with pytest.raises(ConfigError, match="invalid date"):
        load_settings(path, env_file=NO_ENV, environ={})


def test_env_file_read_and_real_env_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=gemini\nGROQ_API_KEY=from-file\n", encoding="utf-8")
    s = load_settings(env_file=env_file, environ={"GROQ_API_KEY": "from-env"})
    assert s.llm.provider == "gemini"
    assert s.secrets.groq_api_key == "from-env"
    assert s.secrets.gemini_api_key is None


def test_secrets_never_in_repr_or_manifest():
    s = load_settings(env_file=NO_ENV, environ={"GROQ_API_KEY": "gsk_secret_value"})
    assert "gsk_secret_value" not in repr(s)
    manifest = s.to_dict()
    assert "secrets" not in manifest
    assert "gsk_secret_value" not in str(manifest)
    assert isinstance(manifest["paths"]["raw"], str)


def test_model_follows_provider_and_models_complete(tmp_path):
    assert load_settings(env_file=NO_ENV, environ={"LLM_PROVIDER": "mock"}).llm.model == "mock"
    path = _write_config(tmp_path, lambda raw: raw["llm"]["models"].pop("gemini"))
    with pytest.raises(ConfigError, match="llm.models"):
        load_settings(path, env_file=NO_ENV, environ={})
