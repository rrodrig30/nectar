"""neo4j driver wrapper (write role).

Thin typed wrapper around the neo4j driver. NutriScrape is the only writer of the shared graph
(DATA_CONTRACT.md Section 0); this client is used by graph/schema.py and graph/writers.py, and by
the acquisition/resolution/nutrition/clustering/knowledge stages that call them. All Cypher is
parameterized here and in graph/writers.py; no other module opens a session directly.

See ../../docs/PDD.md Section 2 (environment and commands) and ../../CLAUDE.md invariants.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import Any, Mapping

from neo4j import Driver, GraphDatabase


class GraphClient:
    """Typed wrapper over a `neo4j.Driver` session, scoped to the writer role.

    Construct via `from_env()` in normal operation. The constructor also accepts an already-built
    `Driver` for tests that supply a fake or a testcontainers-backed instance.
    """

    def __init__(self, driver: Driver, *, database: str | None = None) -> None:
        self._driver = driver
        self._database = database

    @classmethod
    def from_env(cls) -> GraphClient:
        """Build a client from `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` (and optional
        `NEO4J_DATABASE`). See ../../docs/PDD.md Section 2 for the `.env` contract."""
        uri = os.environ["NEO4J_URI"]
        user = os.environ["NEO4J_USER"]
        password = os.environ["NEO4J_PASSWORD"]
        database = os.environ.get("NEO4J_DATABASE")
        driver = GraphDatabase.driver(uri, auth=(user, password))
        return cls(driver, database=database)

    def run(self, cypher: str, **params: Any) -> list[dict[str, Any]]:
        """Execute one parameterized Cypher statement in its own session and return the result
        rows as plain dicts. Callers pass parameters as keyword arguments; never interpolate
        values into `cypher` itself."""
        with self._driver.session(database=self._database) as session:
            result = session.run(cypher, params)
            return [record.data() for record in result]

    def run_write(self, cypher: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Execute one parameterized Cypher statement inside an explicit write transaction.
        Used by graph/writers.py so every write is atomic per statement."""

        def _work(tx: Any) -> list[dict[str, Any]]:
            result = tx.run(cypher, dict(params))
            return [record.data() for record in result]

        with self._driver.session(database=self._database) as session:
            return session.execute_write(_work)

    def apply_schema(self, ddl_path: Path) -> None:
        """Apply the contract DDL at `ddl_path` idempotently. The file is a `;`-separated list of
        Cypher statements (contract/schema/schema.cypher, DATA_CONTRACT.md Section 4). Every
        statement there is `IF NOT EXISTS`, so re-running this is always safe."""
        text = ddl_path.read_text(encoding="utf-8")
        for raw_statement in text.split(";"):
            # Strip full-line `//` comments first: a comment line can share a `;`-delimited
            # chunk with the real statement that follows it (e.g. a file header followed
            # immediately by the first DDL line), so checking the whole chunk for a leading
            # `//` before filtering would wrongly discard that statement.
            lines = [
                line for line in raw_statement.splitlines() if not line.strip().startswith("//")
            ]
            statement = "\n".join(lines).strip()
            if not statement:
                continue
            self.run(statement)

    def close(self) -> None:
        """Close the underlying driver. Safe to call more than once."""
        self._driver.close()

    def __enter__(self) -> GraphClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
