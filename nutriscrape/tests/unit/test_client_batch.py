"""GraphClient.batch() buffers writes and commits them in a single transaction.

Batching per-recipe writes into one commit is the main ingest throughput win at corpus scale
(one fsync per recipe instead of one per statement). This verifies the buffering contract without
a live Neo4j, using a fake driver that records how many write transactions were committed.
"""
from typing import Any

from nutriscrape.graph.client import GraphClient


class _FakeTx:
    def __init__(self, sink: list[tuple[str, dict[str, Any]]]) -> None:
        self._sink = sink

    def run(self, cypher: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        self._sink.append((cypher, params))
        return []


class _FakeSession:
    def __init__(self, driver: "_FakeDriver") -> None:
        self._driver = driver

    def __enter__(self) -> "_FakeSession":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute_write(self, work: Any) -> Any:
        self._driver.commits += 1                 # one commit == one transaction
        return work(_FakeTx(self._driver.statements))


class _FakeDriver:
    def __init__(self) -> None:
        self.commits = 0
        self.statements: list[tuple[str, dict[str, Any]]] = []

    def session(self, database: Any = None) -> _FakeSession:
        return _FakeSession(self)

    def close(self) -> None:
        pass


def test_writes_outside_batch_commit_individually():
    driver = _FakeDriver()
    client = GraphClient(driver)
    client.run_write("MERGE (a)", {"x": 1})
    client.run_write("MERGE (b)", {"x": 2})
    assert driver.commits == 2                    # one transaction each
    assert len(driver.statements) == 2


def test_batch_commits_all_writes_in_one_transaction():
    driver = _FakeDriver()
    client = GraphClient(driver)
    with client.batch():
        client.run_write("MERGE (r:Recipe)", {"id": "r1"})
        client.run_write("MERGE (v:RecipeVariant)", {"id": "v1"})
        client.run_write("MATCH ... MERGE (v)-[:HAS_NUTRIENT]->(n)", {"n": "potassium"})
    assert driver.commits == 1                    # all three in a single transaction
    assert [c for c, _ in driver.statements] == [
        "MERGE (r:Recipe)", "MERGE (v:RecipeVariant)",
        "MATCH ... MERGE (v)-[:HAS_NUTRIENT]->(n)",
    ]                                             # committed in buffered order


def test_empty_batch_commits_nothing():
    driver = _FakeDriver()
    with GraphClient(driver).batch():
        pass
    assert driver.commits == 0


def test_batch_is_not_reentrant():
    client = GraphClient(_FakeDriver())
    with client.batch():
        try:
            with client.batch():
                pass
        except RuntimeError as exc:
            assert "re-entrant" in str(exc)
        else:
            raise AssertionError("nested batch() should raise")
