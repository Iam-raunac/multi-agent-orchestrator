from typing import Literal
from app.config import get_settings
from app.graph.recovery import missing_context, workspace_for

settings = get_settings()


def route_after_validator(state: dict) -> Literal["sandbox", "retry", "fail"]:
    """Decide what happens after Validator runs."""
    if not state.get("validation_passed", False):
        if state.get("retry_count", 0) < settings.max_retries:
            return "retry"
        return "fail"
    return "sandbox"


def route_after_sandbox(state: dict) -> Literal["human_review", "retry", "fail"]:
    """Decide what happens after sandbox test execution."""
    if state.get("tests_passed", False):
        return "human_review"

    if state.get("retry_count", 0) < settings.max_retries:
        return "retry"
    return "fail"


def route_after_human(state: dict) -> Literal["pr_creator", "end"]:
    """Decide what happens after human approval decision."""
    if state.get("human_approved", False):
        return "pr_creator"
    return "end"


def increment_retry(state: dict) -> dict:
    retry = state.get("retry_count", 0) + 1
    stage = state.get("failure_stage") or "validator"
    diagnostic = (
        state.get("test_output", "") if stage == "sandbox"
        else "\n".join(state.get("validation_errors", []))
    )
    chunks = missing_context(state, workspace_for(state))
    locations = ", ".join(f"{item['file_path']}:{item['start_line']}-{item['end_line']}" for item in chunks)
    action = (
        f"retrieve source absent from the previous prompt ({locations})"
        if chunks else f"revise directly ({stage}: no new source frame)"
    )
    return {
        "retry_count": retry,
        "retry_diagnostic": diagnostic[-4000:],
        "recovery_candidates": chunks,
        "events": [{
            "agent": "increment_retry", "type": "completed",
            "summary": f"Retry {retry}: {action}",
        }],
    }


def route_after_retry(state: dict) -> Literal["recover", "redraft"]:
    return "recover" if state.get("recovery_candidates") else "redraft"
