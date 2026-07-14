"""Prefect orchestration for corpus-scale batch runs. Optional: requires Prefect installed.

The stage logic lives in `nutriscrape.pipeline` (Prefect-free); this package only composes those
stages into a DAG and fans the per-recipe ingest out in parallel. See `flows.py`.
"""
