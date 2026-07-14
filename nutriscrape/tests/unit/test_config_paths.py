"""Config and schema path resolution works from a checkout and via env override.

The container run surfaced that resolving these purely relative to __file__ breaks in the installed
(site-packages) layout; these guard the env-override and repo-checkout branches. The cwd fallback is
exercised by the deploy image (config/DDL staged at /app), not unit-testable here without chdir.
"""
import os

from nutriscrape.common.config import default_config_dir, load_env_file
from nutriscrape.graph.schema import find_schema_path


def test_default_config_dir_finds_repo_config():
    assert (default_config_dir() / "nutrients.yaml").is_file()


def test_default_config_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("NUTRISCRAPE_CONFIG", str(tmp_path))
    assert default_config_dir() == tmp_path


def test_find_schema_path_finds_repo_ddl():
    assert find_schema_path().name == "schema.cypher"


def test_find_schema_path_honors_env_override(monkeypatch, tmp_path):
    ddl = tmp_path / "schema.cypher"
    ddl.write_text("// test ddl\n", encoding="utf-8")
    monkeypatch.setenv("NUTRISCRAPE_SCHEMA", str(ddl))
    assert find_schema_path() == ddl


def test_load_env_file_sets_vars_and_respects_existing(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "FDC_API_KEY=abc123\n"
        'export NEO4J_USER="neo4j"\n'
        "NEO4J_PASSWORD='p@ss=w/ord'\n"
        "\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("FDC_API_KEY", raising=False)
    monkeypatch.delenv("NEO4J_PASSWORD", raising=False)
    monkeypatch.setenv("NEO4J_USER", "already-set")  # an exported var must win over the file

    loaded = load_env_file(env)

    assert loaded == env
    assert os.environ["FDC_API_KEY"] == "abc123"
    assert os.environ["NEO4J_USER"] == "already-set"      # not overwritten
    assert os.environ["NEO4J_PASSWORD"] == "p@ss=w/ord"   # quotes stripped, inner '=' kept


def test_load_env_file_absent_is_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("NUTRISCRAPE_ENV_FILE", str(tmp_path / "does-not-exist.env"))
    assert load_env_file() is None
