"""Project settings, loaded once from ``config.yaml`` and ``.env``.

Why this module exists: every other module reads its settings from here, so a
run is fully described by one file (config.yaml) plus a few environment
variables, and the evaluation can record exactly what it ran with
(``Settings.to_dict()`` goes into ``results/run_manifest.json``).

Loading is strict: a missing or unknown key in config.yaml is an error, not a
silent default, so a typo cannot quietly change an experiment.

Environment (``.env`` or real environment variables; real ones win):
  LLM_PROVIDER    overrides ``llm.provider`` (groq | gemini | mock)
  GROQ_API_KEY    secret, never written to repr, logs or the manifest
  GEMINI_API_KEY  secret, same
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml
from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
LLM_PROVIDERS = ("groq", "gemini", "mock")


class ConfigError(ValueError):
    """config.yaml or the environment does not describe a valid run."""


@dataclass(frozen=True)
class Paths:
    raw: Path
    processed: Path
    chroma: Path
    cache: Path
    results: Path


@dataclass(frozen=True)
class DataSettings:
    file_glob: str
    eval_months: tuple[str, ...]


@dataclass(frozen=True)
class EmbeddingSettings:
    model: str
    max_tokens: int
    batch_size: int


@dataclass(frozen=True)
class RetrievalSettings:
    top_k: int


@dataclass(frozen=True)
class LLMSettings:
    provider: str
    model: str | None
    temperature: float
    max_output_tokens: int
    timeout_s: int
    retries: int


@dataclass(frozen=True)
class BaselineSettings:
    timeout_s: int


@dataclass(frozen=True)
class EvalSettings:
    rel_tolerance: float
    abs_tolerance_pct_points: float
    manual_check_n: int
    seed: int


@dataclass(frozen=True)
class Secrets:
    groq_api_key: str | None = field(default=None, repr=False)
    gemini_api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Settings:
    paths: Paths
    data: DataSettings
    embedding: EmbeddingSettings
    retrieval: RetrievalSettings
    llm: LLMSettings
    chunking: dict[str, dict[str, Any]]  # per-chunker options; each chunker validates its own
    baseline: BaselineSettings
    eval: EvalSettings
    config_file: Path
    secrets: Secrets = field(default_factory=Secrets, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Plain dict of everything except secrets, for the run manifest."""
        out = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "secrets"}
        out = {k: asdict(v) if hasattr(v, "__dataclass_fields__") else v for k, v in out.items()}
        return _stringify_paths(out)


def _stringify_paths(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {k: _stringify_paths(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_stringify_paths(v) for v in value]
    return value


def _section(raw: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if not isinstance(value, dict):
        raise ConfigError(f"config section '{name}' is missing or not a mapping")
    return value


def _build(cls: type, values: dict[str, Any], section: str) -> Any:
    """Build a settings dataclass, failing on missing or unknown keys."""
    expected = {f.name for f in fields(cls)}
    missing = expected - values.keys()
    unknown = values.keys() - expected
    if missing:
        raise ConfigError(f"config section '{section}' is missing keys: {sorted(missing)}")
    if unknown:
        raise ConfigError(f"config section '{section}' has unknown keys: {sorted(unknown)}")
    return cls(**values)


def _resolve(path_value: str, base: Path) -> Path:
    p = Path(path_value).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def load_settings(
    config_path: Path | str | None = None,
    env_file: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Read config.yaml and the environment into a Settings object.

    ``environ`` defaults to ``os.environ``; tests pass their own dict. Values in
    ``environ`` win over values in ``env_file``. Nothing here modifies os.environ.
    """
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG
    env_file = Path(env_file) if env_file else DEFAULT_ENV_FILE
    environ = os.environ if environ is None else environ

    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a mapping at the top level")

    known = {"paths", "data", "embedding", "retrieval", "llm", "chunking", "baseline", "eval"}
    unknown = raw.keys() - known
    if unknown:
        raise ConfigError(f"config has unknown top-level sections: {sorted(unknown)}")

    env: dict[str, str] = {k: v for k, v in dotenv_values(env_file).items() if v is not None} \
        if env_file.is_file() else {}
    env.update({k: v for k, v in environ.items() if k in ("LLM_PROVIDER", "GROQ_API_KEY", "GEMINI_API_KEY")})

    base = config_path.resolve().parent
    paths_raw = _section(raw, "paths")
    paths = _build(Paths, {k: _resolve(str(v), base) for k, v in paths_raw.items()}, "paths")

    data_raw = dict(_section(raw, "data"))
    months = data_raw.get("eval_months")
    if not isinstance(months, list) or not months:
        raise ConfigError("data.eval_months must be a non-empty list of YYYY-MM-DD dates")
    for m in months:
        try:
            date.fromisoformat(str(m))
        except ValueError:
            raise ConfigError(f"data.eval_months has an invalid date: {m!r}") from None
    data_raw["eval_months"] = tuple(str(m) for m in months)
    data = _build(DataSettings, data_raw, "data")

    llm_raw = dict(_section(raw, "llm"))
    if env.get("LLM_PROVIDER"):
        llm_raw["provider"] = env["LLM_PROVIDER"].strip().lower()
    llm = _build(LLMSettings, llm_raw, "llm")
    if llm.provider not in LLM_PROVIDERS:
        raise ConfigError(f"llm.provider must be one of {LLM_PROVIDERS}, got {llm.provider!r}")

    chunking = _section(raw, "chunking")

    return Settings(
        paths=paths,
        data=data,
        embedding=_build(EmbeddingSettings, _section(raw, "embedding"), "embedding"),
        retrieval=_build(RetrievalSettings, _section(raw, "retrieval"), "retrieval"),
        llm=llm,
        chunking={name: dict(opts or {}) for name, opts in chunking.items()},
        baseline=_build(BaselineSettings, _section(raw, "baseline"), "baseline"),
        eval=_build(EvalSettings, _section(raw, "eval"), "eval"),
        config_file=config_path.resolve(),
        secrets=Secrets(
            groq_api_key=env.get("GROQ_API_KEY") or None,
            gemini_api_key=env.get("GEMINI_API_KEY") or None,
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The project's settings, loaded once per process from the default files."""
    return load_settings()
