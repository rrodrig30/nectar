# NECTAR web

React + TypeScript frontend (Vite). Screens to build (see ../docs/SDD.md Section 6, 10.2):
- Profile builder: conditions, medications, labs, allergies, objective data, goal.
- Confirmation view: every derived constraint with its source_signal and formula, editable.
- Results: suitability per condition, per-serving nutrients vs limits, conflict notices.
- Evidence panel: guideline passages behind each verdict.
- Persistent (non-dismissible) intended-use boundary banner.
- Unit-system (US/metric) and temperature (F/C) toggles, applied at display time.

Build outputs to dist/ and is served by nginx-unprivileged (see Containerfile).
