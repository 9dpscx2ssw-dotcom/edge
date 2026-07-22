"""Regression guards for Oracle's separate account and Shadow books."""
from __future__ import annotations

import ast
from pathlib import Path

AGENT_SOURCE = Path(__file__).parents[1] / "src/gungnir/core/agent.py"


def _method(name: str) -> ast.AsyncFunctionDef:
    tree = ast.parse(AGENT_SOURCE.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing async method {name}")


def test_live_and_shadow_netters_use_distinct_persisted_books():
    """Live account state must never load/write the Shadow attribution ledger."""
    tree = ast.parse(AGENT_SOURCE.read_text())
    paths = {
        kw.value.value
        for node in ast.walk(tree) if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "virtual_books_path" and isinstance(kw.value, ast.Constant)
    }
    assert "data/account_virtual_books.json" in paths
    assert "data/shadow_virtual_books.json" in paths
    assert "data/virtual_books.json" not in paths


def test_shadow_consensus_looks_up_position_in_execution_book():
    """Shadow consensus must see its existing Shadow consensus position."""
    method = _method("_consensus_step")
    exec_line = next(
        stmt.lineno for stmt in method.body
        if isinstance(stmt, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "_exec_broker" for t in stmt.targets)
    )
    calls = [
        node for node in ast.walk(method)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "position" and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant) and node.args[1].value == "consensus"
    ]
    assert len(calls) == 1
    assert isinstance(calls[0].func.value, ast.Name)
    assert calls[0].func.value.id == "_exec_broker"
    assert exec_line < calls[0].lineno


def test_same_side_held_signal_is_not_recorded_as_new_shadow_execution():
    """A position reaffirmation is telemetry, not another Shadow trade."""
    method = _method("_process_symbol")
    assert any(isinstance(node, ast.Constant) and node.value == "held_existing"
               for node in ast.walk(method))
