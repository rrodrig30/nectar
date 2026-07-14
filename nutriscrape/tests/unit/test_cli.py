"""Unit tests for CLI stage dispatch (`python -m nutriscrape <stage>`).

Every pipeline function is monkeypatched to a no-op recorder, so these tests only exercise argv
parsing and dispatch order; no live Neo4j, FDC, or model service is ever touched.
"""
from __future__ import annotations

from collections.abc import Callable

import pytest

from nutriscrape import __main__ as cli
from nutriscrape import pipeline

_STAGE_FUNC_NAMES = ("run_schema", "run_knowledge", "run_fdc_import", "run_ingest",
                     "run_cluster", "run_materialize")

_RUN_ALL_EXPECTED = [
    "run_schema", "run_knowledge", "run_fdc_import", "run_ingest", "run_cluster", "run_materialize",
]


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace every `pipeline.run_*` function with a no-op that records its own name, in order."""
    calls: list[str] = []

    def _recording_stub(name: str) -> Callable[[], None]:
        def _stub() -> None:
            calls.append(name)

        return _stub

    for name in _STAGE_FUNC_NAMES:
        monkeypatch.setattr(pipeline, name, _recording_stub(name))
    return calls


def test_unknown_stage_returns_exit_code_2() -> None:
    assert cli.main(["prog", "bogus-stage"]) == 2


@pytest.mark.parametrize(
    ("stage", "expected_func"),
    [
        ("schema", "run_schema"),
        ("knowledge", "run_knowledge"),
        ("fdc-import", "run_fdc_import"),
        ("ingest", "run_ingest"),
        ("cluster", "run_cluster"),
        ("materialize", "run_materialize"),
    ],
)
def test_known_stage_dispatches_to_matching_pipeline_function(
    recorder: list[str], stage: str, expected_func: str
) -> None:
    exit_code = cli.main(["prog", stage])
    assert exit_code == 0
    assert recorder == [expected_func]


def test_run_all_calls_stages_in_order(recorder: list[str]) -> None:
    exit_code = cli.main(["prog", "run-all"])
    assert exit_code == 0
    assert recorder == _RUN_ALL_EXPECTED


def test_default_argv_dispatches_run_all(recorder: list[str]) -> None:
    exit_code = cli.main(["prog"])
    assert exit_code == 0
    assert recorder == _RUN_ALL_EXPECTED


def test_stage_failure_is_caught_and_returns_exit_code_1(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(pipeline, "run_schema", _boom)
    assert cli.main(["prog", "schema"]) == 1
