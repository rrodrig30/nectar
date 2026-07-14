"""Typed config loading from config/*.yaml with ${VAR:-default} env expansion. I/O boundary.

Source terms, nutrient vocabulary, attribute tags, and transform coefficients live in config/ and are
loaded here. Secrets are never committed; only .env.example is. See PDD Section 1, SDD Section 3.1.
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def repl(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1)) or (m.group(2) or "")
        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def default_config_dir() -> Path:
    """The nutriscrape/config directory, resolved relative to this file (cwd-independent)."""
    return Path(__file__).resolve().parents[3] / "config"


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Load one YAML document with env expansion applied. Returns an empty dict for an empty file."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    expanded = _expand(data if data is not None else {})
    if not isinstance(expanded, dict):
        raise ValueError(f"expected a mapping at the top level of {path}")
    return expanded


def load_config(name: str, config_dir: str | Path | None = None) -> dict[str, Any]:
    """Load config/<name>.yaml (name may include a subpath, for example 'transforms/potato')."""
    base = Path(config_dir) if config_dir is not None else default_config_dir()
    fname = name if name.endswith((".yaml", ".yml")) else f"{name}.yaml"
    return load_yaml(base / fname)
