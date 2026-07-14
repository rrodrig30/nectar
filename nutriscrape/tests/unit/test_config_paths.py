"""Config and schema path resolution works from a checkout and via env override.

The container run surfaced that resolving these purely relative to __file__ breaks in the installed
(site-packages) layout; these guard the env-override and repo-checkout branches. The cwd fallback is
exercised by the deploy image (config/DDL staged at /app), not unit-testable here without chdir.
"""
from nutriscrape.common.config import default_config_dir
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
