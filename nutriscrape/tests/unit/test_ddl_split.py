"""Unit tests for DDL statement splitting (regression: a semicolon inside a // comment)."""
from nutriscrape.graph.client import split_ddl_statements


def test_semicolon_inside_a_comment_does_not_break_the_statement():
    ddl = (
        "CREATE CONSTRAINT rule_id IF NOT EXISTS FOR (dr:DietaryRule) REQUIRE dr.rule_id IS UNIQUE;\n"
        "// prep_id is unique per (recipe, food); without this MERGE (:Preparation) full-scans,\n"
        "// which is O(n^2) at corpus scale.\n"
        "CREATE CONSTRAINT prep_id IF NOT EXISTS FOR (p:Preparation) REQUIRE p.prep_id IS UNIQUE;\n"
    )
    statements = split_ddl_statements(ddl)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE CONSTRAINT rule_id")
    assert statements[1].startswith("CREATE CONSTRAINT prep_id")
    # the comment tail must not leak into a statement
    assert not any("without this" in s for s in statements)


def test_full_line_comments_and_blanks_are_dropped():
    ddl = "// a header comment\n\nCREATE INDEX foo IF NOT EXISTS FOR (n:N) ON (n.x);\n// trailing\n"
    statements = split_ddl_statements(ddl)
    assert statements == ["CREATE INDEX foo IF NOT EXISTS FOR (n:N) ON (n.x)"]


def test_inline_trailing_comment_is_stripped():
    ddl = "CREATE INDEX v_g IF NOT EXISTS FOR (v:V) ON (v.g);  // glycemic load index\n"
    assert split_ddl_statements(ddl) == ["CREATE INDEX v_g IF NOT EXISTS FOR (v:V) ON (v.g)"]
