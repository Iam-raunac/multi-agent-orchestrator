from app.agents.base import BaseAgent
from app.llm.router import llm_router

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text

SYSTEM_PROMPT = """You are an expert software engineer who writes precise code fixes.

You will receive:
1. An issue analysis (module, severity, expected vs actual behavior)
2. Relevant code chunks from the repository

Your job: produce a unified diff (patch format) that fixes the issue.

Rules:
- Output ONLY the diff, no explanation, no markdown fences
- Use standard unified diff format starting with `--- a/path/to/file.py`
- Include 3 lines of context above and below each change
- Make minimal, targeted changes — do not refactor unrelated code
- If you cannot determine the fix from the given context, output: NO_FIX_POSSIBLE"""


class FixDrafterAgent(BaseAgent):
    name = "fix_drafter"

    async def run(self, state: dict) -> dict:
        analysis = state.get("issue_analysis", {})
        code_context = state.get("code_context", "")
        retry_count = state.get("retry_count", 0)

        # If this is a retry, include previous test failures so LLM can learn from them
        retry_hint = ""
        if retry_count > 0:
            previous_diff = state.get("proposed_diff", "")[-6000:]
            diagnostic = state.get("retry_diagnostic") or state.get("test_output", "")[-4000:]
            retry_hint = (
                f"\n\nPrevious candidate (may be truncated):\n{previous_diff}"
                f"\n\nFailure diagnostics:\n{diagnostic}"
                "\nUse any recovered source to revise the candidate. Generate a complete diff "
                "against the original checkout, since the previous candidate is not applied."
            )

        user_message = f"""Issue analysis:
{analysis}

Relevant code:
{code_context}
{retry_hint}

Write the unified diff to fix this issue."""

        diff = await llm_router.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            task="code",
        )
        diff = _strip_fences(diff)

        return {
            "proposed_diff": diff.strip(),
            "events": [{
                "agent": self.name,
                "type": "completed",
                "summary": f"Generated diff ({len(diff)} chars, attempt #{retry_count + 1})",
            }],
        }


fix_drafter = FixDrafterAgent()