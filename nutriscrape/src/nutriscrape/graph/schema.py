"""Apply contract/schema/schema.cypher idempotently.

The DDL is the canonical schema from DATA_CONTRACT.md Section 4: it lives once, in the shared
`contract/` package, and is not redefined here. `make schema` calls `apply_schema` below with a
`GraphClient` built from the environment. See ../../docs/PDD.md Section 2.
"""
from __future__ import annotations

from pathlib import Path

from nutriscrape.graph.client import GraphClient

_SCHEMA_RELATIVE_PATH = Path("contract") / "schema" / "schema.cypher"


def find_schema_path(start: Path | None = None) -> Path:
    """Locate `contract/schema/schema.cypher` by walking up from `start` (default: this file)
    until a `contract/schema/schema.cypher` is found. Raises `FileNotFoundError` if the monorepo
    root cannot be located, so a misconfigured checkout fails loudly rather than silently."""
    here = (start or Path(__file__)).resolve()
    for candidate_root in (here, *here.parents):
        candidate = candidate_root / _SCHEMA_RELATIVE_PATH
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"could not locate {_SCHEMA_RELATIVE_PATH} above {here}; "
        "expected a monorepo checkout with a sibling contract/ package"
    )


def apply_schema(client: GraphClient, ddl_path: Path | None = None) -> None:
    """Apply the contract DDL through `client`. `ddl_path` defaults to the schema file discovered
    by `find_schema_path`. Idempotent: every statement in the DDL is `IF NOT EXISTS`."""
    path = ddl_path if ddl_path is not None else find_schema_path()
    client.apply_schema(path)
