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
_CONFIG_ENV_VAR = "NUTRISCRAPE_CONFIG"


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
    """The nutriscrape/config directory. Resolution order: the `NUTRISCRAPE_CONFIG` env var if set;
    then the `config/` sibling of the source tree (editable / monorepo layout); then `config/` under
    the working directory (installed-package / container layout, where config is staged next to the
    app). This keeps config discoverable whether run from a checkout or an installed wheel."""
    override = os.environ.get(_CONFIG_ENV_VAR)
    if override:
        return Path(override)
    relative = Path(__file__).resolve().parents[3] / "config"
    if relative.is_dir():
        return relative
    return Path.cwd() / "config"


_ENV_FILE_VAR = "NUTRISCRAPE_ENV_FILE"


def load_env_file(path: str | Path | None = None) -> Path | None:
    """Load a `.env` file (`KEY=value` lines) into `os.environ` for local runs, with no dependency.

    Resolution order: the `path` argument; then `NUTRISCRAPE_ENV_FILE`; then the first `.env` found
    walking up from the working directory to the filesystem root (the monorepo root holds it). An
    already-set environment variable always wins (we never overwrite), so a value exported in the
    shell or injected by a container `--env-file` is never clobbered by the file. Returns the loaded
    path, or None when no file is found, so this is a safe no-op in container deployments that inject
    the environment directly. Supports an optional `export ` prefix, `#` comments, and single- or
    double-quoted values. It is the entry points' job to call this before reading the environment.
    """
    candidate = _resolve_env_file(path)
    if candidate is None or not candidate.is_file():
        return None
    for raw_line in candidate.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    return candidate


def _resolve_env_file(path: str | Path | None) -> Path | None:
    if path is not None:
        return Path(path)
    override = os.environ.get(_ENV_FILE_VAR)
    if override:
        return Path(override)
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


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
