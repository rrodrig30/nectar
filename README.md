# NECTAR Platform

[![CI](https://github.com/rrodrig30/nectar/actions/workflows/ci.yml/badge.svg)](https://github.com/rrodrig30/nectar/actions/workflows/ci.yml)

Nutritional Evidence and Clinical Targeting of Appropriate Recipes. A knowledge-graph and
retrieval-augmented platform that builds a nutrition database from recipes and food-composition
data, and recommends dishes appropriate to a patient's conditions, medications, and goals.

**Educational and research use only. Not medical nutrition therapy.** See `LICENSE-NOTES.md`
and `nectar/docs/SDD.md` Section 9 for the intended-use boundary and validation gate.

## Two programs, one contract

- `contract/` — the shared Neo4j hybrid (graph + vector) schema and write-back interface. The
  single source of truth both programs depend on. Start here: `contract/DATA_CONTRACT.md`.
- `nutriscrape/` — the batch data engine. Builds the database. No interactive user.
- `nectar/` — the clinician-facing application. Reads the database, composes per patient.
- `deploy/` — rootless Podman deployment (Quadlet units, Containerfiles, compose, Caddy, RBAC).

NutriScrape writes the graph. NECTAR reads it and performs exactly one gated write-back. The
dependency direction is fixed and enforced by Neo4j roles (`deploy/neo4j/init-roles.cypher`).

## Working in Claude Code

Open the repo root so the root `CLAUDE.md` loads. It imports the contract and points at each
program's `CLAUDE.md`. The invariants in those files are non-negotiable; they encode the clinical
safety design. Build order and acceptance criteria are in each program's `docs/PDD.md` Section
"Phased Task Plan".

## Quick start (development)

```bash
cp .env.example .env
cd deploy/compose && podman-compose up -d neo4j ollama       # infra
# build + run each program per its Makefile; see nutriscrape/ and nectar/
```

Production deployment: `deploy/README.md`.
