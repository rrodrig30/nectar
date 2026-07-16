"""neo4j driver wrapper (write role).

Thin typed wrapper around the neo4j driver. NutriScrape is the only writer of the shared graph
(DATA_CONTRACT.md Section 0); this client is used by graph/schema.py and graph/writers.py, and by
the acquisition/resolution/nutrition/clustering/knowledge stages that call them. All Cypher is
parameterized here and in graph/writers.py; no other module opens a session directly.

See ../../docs/PDD.md Section 2 (environment and commands) and ../../CLAUDE.md invariants.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Any, Mapping

from neo4j import Driver, GraphDatabase


def split_ddl_statements(text: str) -> list[str]:
    """Split a `;`-separated Cypher DDL file into individual statements.

    `//` comments are stripped to end of line BEFORE splitting on `;`, because a comment may itself
    contain a semicolon (e.g. `// unique per (recipe, food); without this ...`). Splitting first
    would break the statement at that semicolon and leave the comment's tail polluting the next
    statement, producing a syntax error. Empty statements are dropped.
    """
    without_comments = "\n".join(line.split("//", 1)[0] for line in text.splitlines())
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


class GraphClient:
    """Typed wrapper over a `neo4j.Driver` session, scoped to the writer role.

    Construct via `from_env()` in normal operation. The constructor also accepts an already-built
    `Driver` for tests that supply a fake or a testcontainers-backed instance.
    """

    def __init__(self, driver: Driver, *, database: str | None = None) -> None:
        self._driver = driver
        self._database = database
        # When inside a `batch()` context, `run_write` appends here instead of committing, so a whole
        # unit of work (e.g. one recipe's writes) commits in a single transaction. None means writes
        # commit immediately (one transaction each), the default everywhere except batched ingest.
        self._batch: list[tuple[str, Mapping[str, Any]]] | None = None

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
        Used by graph/writers.py so every write is atomic per statement. Inside a `batch()` context
        the statement is buffered and committed with the rest of the batch instead; buffered writes
        return no rows (ingest writers do not read their results)."""
        if self._batch is not None:
            self._batch.append((cypher, params))
            return []

        def _work(tx: Any) -> list[dict[str, Any]]:
            result = tx.run(cypher, dict(params))
            return [record.data() for record in result]

        with self._driver.session(database=self._database) as session:
            return session.execute_write(_work)

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Buffer every `run_write` in the block and commit them in ONE transaction on exit.

        At corpus scale the per-recipe write set is ~dozens of statements; committing each in its own
        transaction makes the fsync-per-commit the throughput ceiling. Grouping a recipe's writes
        into a single transaction amortizes that commit and is the main ingest speedup. Statements
        run in the order buffered, so intra-recipe dependencies (a variant merged before its
        HAS_NUTRIENT edges) hold. Not nestable. Reads (`run`) are unaffected and still execute live.
        """
        if self._batch is not None:
            raise RuntimeError("GraphClient.batch() is not re-entrant")
        buffer: list[tuple[str, Mapping[str, Any]]] = []
        self._batch = buffer
        try:
            yield
        finally:
            self._batch = None
        if not buffer:
            return

        def _work(tx: Any) -> None:
            for cypher, params in buffer:
                tx.run(cypher, dict(params))

        with self._driver.session(database=self._database) as session:
            session.execute_write(_work)

    def apply_schema(self, ddl_path: Path) -> None:
        """Apply the contract DDL at `ddl_path` idempotently. The file is a `;`-separated list of
        Cypher statements (contract/schema/schema.cypher, DATA_CONTRACT.md Section 4). Every
        statement there is `IF NOT EXISTS`, so re-running this is always safe."""
        for statement in split_ddl_statements(ddl_path.read_text(encoding="utf-8")):
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
