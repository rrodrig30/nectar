"""CLI dispatch for batch stages. Usage: python -m nutriscrape <stage>
stages: schema | knowledge | fdc-import | ingest | cluster | materialize | run-all
"""
from __future__ import annotations

import logging
import sys

from nutriscrape import pipeline

STAGES = ("schema", "knowledge", "fdc-import", "ingest", "cluster", "materialize", "run-all")

# Stage name -> the pipeline function that implements it. `run-all` is not a key here; it is the
# ordered sequence of the other stages, defined in _RUN_ALL_ORDER (docs/PDD.md Section 10).
_STAGE_TO_FUNC_NAME: dict[str, str] = {
    "schema": "run_schema",
    "knowledge": "run_knowledge",
    "fdc-import": "run_fdc_import",
    "ingest": "run_ingest",
    "cluster": "run_cluster",
    "materialize": "run_materialize",
}

# fdc-import runs before ingest so ingest can resolve against the local :Food graph rather than the
# FDC API. It no-ops (logs) when FDC_BULK_DIR is unset, so run-all is safe without a bulk export.
_RUN_ALL_ORDER: tuple[str, ...] = (
    "schema", "knowledge", "fdc-import", "ingest", "cluster", "materialize",
)

logger = logging.getLogger(__name__)


def _run_stage(stage: str) -> None:
    """Dispatch one non-'run-all' stage name to its pipeline function.

    Looks the function up on the `pipeline` module by name at call time (rather than binding a
    dict of function objects at import time) so tests can monkeypatch `pipeline.run_*` directly.
    """
    func_name = _STAGE_TO_FUNC_NAME[stage]
    func = getattr(pipeline, func_name)
    func()


def main(argv: list[str]) -> int:
    stage = argv[1] if len(argv) > 1 else "run-all"
    if stage not in STAGES:
        print(f"unknown stage {stage!r}; choose from {STAGES}", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO)

    try:
        if stage == "run-all":
            for name in _RUN_ALL_ORDER:
                _run_stage(name)
        else:
            _run_stage(stage)
    except Exception:
        logger.exception("stage %r failed", stage)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
