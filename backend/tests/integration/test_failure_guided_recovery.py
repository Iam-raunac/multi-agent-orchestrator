"""Run the actual graph and pytest gate with deterministic test dependencies."""
import asyncio
import os
from difflib import unified_diff
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver
import pytest


FIXTURE = """from shipping.rules import fee_cap


def quote(region, weight):
    gross = 5 + 5 * weight
    return min(gross, fee_cap(region))
"""
RULES = """def fee_cap(region):
    caps = {"local": 10, "remote": 20}
    return caps[region.lower()]
"""
TESTS = """from shipping.quote import quote


def test_local_alias():
    assert quote("city", 2) == 10


def test_local_small():
    assert quote("local", 0) == 5


def test_remote():
    assert quote("remote", 2) == 15
"""


def make_diff(source, revised):
    return "".join(unified_diff(
        source.splitlines(keepends=True), revised.splitlines(keepends=True),
        "a/shipping/quote.py", "b/shipping/quote.py",
    ))


class FixtureExecutor:
    async def run_command(self, command, files):
        # Only execute the synthetic fixture compiled into this test.
        with TemporaryDirectory() as temp:
            root = Path(temp)
            for name, content in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            env = dict(
                os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
                PATH=f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}",
            )
            result = subprocess.run(
                command, cwd=root, text=True, capture_output=True, timeout=20, env=env,
            )
            return {"exit_code": result.returncode, "output": result.stdout + result.stderr}


@pytest.mark.parametrize("initially_visible", [False, True], ids=["recover", "direct-retry"])
def test_graph_retries_with_missing_repository_context(
    monkeypatch, tmp_path, initially_visible,
):
    monkeypatch.setenv("GROQ_API_KEY", "test-fixture")
    monkeypatch.setenv("GITHUB_TOKEN", "test-fixture")
    root = tmp_path
    (root / "shipping").mkdir()
    (root / "shipping/quote.py").write_text(FIXTURE, encoding="utf-8")
    (root / "shipping/rules.py").write_text(RULES, encoding="utf-8")
    prompts = []

    async def complete(messages, task, json_mode=False):
        if json_mode:
            return {
                "module": "shipping", "severity": "low", "repro_steps": ["quote city"],
                "expected_behavior": "Treat city as local", "actual_behavior": "KeyError",
                "keywords": ["shipping", "quote", "region"],
            }
        if messages[-1]["content"].endswith("Write pytest tests."):
            return TESTS
        prompt = messages[-1]["content"]
        prompts.append(prompt)
        if len(prompts) == 1:
            return make_diff(FIXTURE, FIXTURE.replace("fee_cap(region)", "fee_cap(region.strip())"))
        assert "Failure diagnostics" in prompt and "KeyError: 'city'" in prompt
        assert 'caps = {"local": 10, "remote": 20}' in prompt
        assert ("# Recovered: shipping/rules.py" in prompt) != initially_visible
        return make_diff(FIXTURE, FIXTURE.replace(
            "fee_cap(region)", 'fee_cap("local" if region == "city" else region)',
        ))

    chunks = [{
        "file_path": str(root / "shipping/quote.py"),
        "start_line": 1, "end_line": len(FIXTURE.splitlines()), "content": FIXTURE,
    }]
    if initially_visible:
        chunks.append({
            "file_path": "shipping/rules.py",
            "start_line": 1, "end_line": len(RULES.splitlines()), "content": RULES,
        })

    async def no_pr(_state):
        raise AssertionError("Fixture must stop at human review")

    dependencies = {
        "app.llm.router": SimpleNamespace(llm_router=SimpleNamespace(complete=complete)),
        "app.rag.retriever": SimpleNamespace(retriever=SimpleNamespace(search=lambda **_: chunks)),
        "app.sandbox.executor": SimpleNamespace(sandbox=FixtureExecutor()),
        "app.agents.pr_creator": SimpleNamespace(pr_creator=no_pr),
    }
    with patch.dict(sys.modules, dependencies):
        for name in list(sys.modules):
            if name == "app" or (
                name.startswith(("app.agents", "app.graph", "app.sandbox"))
                and name not in dependencies
            ):
                sys.modules.pop(name)
        from app.graph import builder, edges

        monkeypatch.setattr(builder, "workspace_for", lambda _: root)
        monkeypatch.setattr(edges, "workspace_for", lambda _: root)
        # Check the actual validator's control flow without requiring lint binaries at runtime.
        monkeypatch.setattr(builder.validator, "_run_mypy", lambda _: [])
        monkeypatch.setattr(builder.validator, "_run_pylint", lambda _: [])

        async def run():
            graph = builder.compile_graph(InMemorySaver())
            config = {"configurable": {"thread_id": "shipping-fixture"}}
            events = [event async for event in graph.astream(
                {"repo_full_name": "fixture/shipping", "issue_title": "City alias",
                 "retry_count": 0, "events": []}, config,
            )]
            invalid = await builder.run_tests(TESTS, repo_path=root, diff="malformed patch")
            assert invalid["exit_code"] == 10 and not invalid["tests_passed"]
            assert invalid["summary"]["total"] == 0
            return events, await graph.aget_state(config)

        updates, snapshot = asyncio.run(run())

    path = [next(iter(event)) for event in updates if "__interrupt__" not in event]
    results = [event["sandbox"] for event in updates if "sandbox" in event]
    recoveries = [
        e["codebase_explorer"]["events"][0]["summary"]
        for e in updates if "codebase_explorer" in e
        and e["codebase_explorer"].get("recovered_context")
    ]
    assert [item["sandbox_exit_code"] for item in results] == [1, 0], [item["test_output"] for item in results]
    assert [item["tests_passed"] for item in results] == [False, True]
    assert snapshot.values["retry_count"] == 1
    assert snapshot.next == ("human_review",)
    assert len(prompts) == 2
    assert path.count("codebase_explorer") == (1 if initially_visible else 2)
    assert recoveries == ([] if initially_visible else ["Recovered shipping/rules.py:1-3 (fee_cap)"])
    retry_event = next(e["increment_retry"]["events"][0]["summary"] for e in updates if "increment_retry" in e)
    print(f"Route: {' -> '.join(path)}")
    print(results[0]["events"][0]["summary"], "exit=1")
    print(next(line for line in results[0]["test_output"].splitlines() if "KeyError: 'city'" in line))
    print(retry_event)
    for event in recoveries:
        print(event)
    print(results[1]["events"][0]["summary"], "exit=0")
    print("Graph paused at human_review")
