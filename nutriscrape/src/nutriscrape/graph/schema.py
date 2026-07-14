"""Apply contract/schema/schema.cypher idempotently.

The DDL is the canonical schema from DATA_CONTRACT.md Section 4: it lives once, in the shared
`contract/` package, and is not redefined here. `make schema` calls `apply_schema` below with a
`GraphClient` built from the environment. See ../../docs/PDD.md Section 2.
"""
from __future__ import annotations

import os
from pathlib import Path

from nutriscrape.graph.client import GraphClient

_SCHEMA_RELATIVE_PATH = Path("contract") / "schema" / "schema.cypher"
_SCHEMA_ENV_VAR = "NUTRISCRAPE_SCHEMA"


def find_schema_path(start: Path | None = None) -> Path:
    """Locate `contract/schema/schema.cypher`. Search order: the `NUTRISCRAPE_SCHEMA` env var if set;
    then walking up from `start`/this file (a monorepo or editable checkout); then
    `contract/schema/schema.cypher` under the working directory (the installed-package / container
    layout, where the DDL is staged next to the app). Raises `FileNotFoundError` if none is found, so
    a misconfigured deployment fails loudly rather than silently."""
    override = os.environ.get(_SCHEMA_ENV_VAR)
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise FileNotFoundError(f"{_SCHEMA_ENV_VAR}={override!r} does not point at a file")

    here = (start or Path(__file__)).resolve()
    for candidate_root in (here, *here.parents, Path.cwd()):
        candidate = candidate_root / _SCHEMA_RELATIVE_PATH
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"could not locate {_SCHEMA_RELATIVE_PATH} from {here} or {Path.cwd()}; set "
        f"{_SCHEMA_ENV_VAR} to the schema.cypher path, or run from a checkout with a contract/ dir"
    )


def apply_schema(client: GraphClient, ddl_path: Path | None = None) -> None:
    """Apply the contract DDL through `client`. `ddl_path` defaults to the schema file discovered
    by `find_schema_path`. Idempotent: every statement in the DDL is `IF NOT EXISTS`."""
    path = ddl_path if ddl_path is not None else find_schema_path()
    client.apply_schema(path)
