# Failure-guided context recovery

A pytest test failure can route a retry through Codebase Explorer when its
traceback points to an uncovered Python source span in the local checkout.
The explorer appends a bounded excerpt. The drafter sees the prior candidate,
the diagnostics and the expanded source. Validation and patch application
errors take the direct retry route. The existing retry limit and review gate
apply to both paths.

The sandbox applies one diff to fresh source and requires a zero pytest exit
status, at least one passing test and no reported failures or errors. It runs
without a network connection. The application continues to use the base
checkout at /tmp/<repository-name> and the existing semantic index for the
first attempt. Prepare both against the same revision before a live run.

From backend/, activate a Python 3.12 environment and run:

    python -m pip install langgraph pydantic-settings structlog pytest pytest-asyncio
    python -m pytest -q -s tests/integration/test_failure_guided_recovery.py

The integration test runs the real LangGraph, Explorer, Drafter prompt code,
patch/pytest runner and review interrupt. A controlled local executor runs
only the synthetic shipping fixture. The model and initial search are test
doubles. No credentials, Docker service or GitHub writes are required for this
test. It covers recovery of an omitted helper, direct redrafting if already
visible, and patch application failure before tests can run.
