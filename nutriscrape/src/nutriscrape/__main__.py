"""CLI dispatch for batch stages. Usage: python -m nutriscrape <stage>
stages: schema | knowledge | fdc-import | ingest | cluster | materialize | run-all | flow

`run-all` runs the stages sequentially in one process. `flow` runs the same work as a Prefect DAG
with the ingest step fanned out over parallel batches (needs the optional prefect dependency).
"""
from __future__ import annotations

import logging
import sys

from nutriscrape import pipeline
from nutriscrape.common.config import load_env_file

STAGES = (
    "schema", "knowledge", "fdc-import", "ingest", "bulk-export", "bulk-load",
    "cluster", "materialize", "dish-stats", "run-all", "flow",
)

# Stage name -> the pipeline function that implements it. `run-all` is not a key here; it is the
# ordered sequence of the other stages, defined in _RUN_ALL_ORDER (docs/PDD.md Section 10).
_STAGE_TO_FUNC_NAME: dict[str, str] = {
    "schema": "run_schema",
    "knowledge": "run_knowledge",
    "fdc-import": "run_fdc_import",
    "ingest": "run_ingest",
    "bulk-export": "run_bulk_export",
    "bulk-load": "run_bulk_load",
    "cluster": "run_cluster",
    "materialize": "run_materialize",
    "dish-stats": "run_dish_stats",
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


def _run_flow() -> None:
    """Run the Prefect orchestration flow. Imported lazily so the other stages never need prefect."""
    from nutriscrape.orchestration.flows import nutriscrape_flow

    nutriscrape_flow()


def main(argv: list[str]) -> int:
    stage = argv[1] if len(argv) > 1 else "run-all"
    if stage not in STAGES:
        print(f"unknown stage {stage!r}; choose from {STAGES}", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO)
    env_file = load_env_file()  # local .env; a no-op when env is injected (containers)
    if env_file is not None:
        logger.info("loaded environment from %s", env_file)

    try:
        if stage == "run-all":
            for name in _RUN_ALL_ORDER:
                _run_stage(name)
        elif stage == "flow":
            _run_flow()
        else:
            _run_stage(stage)
    except Exception:
        logger.exception("stage %r failed", stage)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
