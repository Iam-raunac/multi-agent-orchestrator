from app.agents.base import BaseAgent
from app.llm.router import llm_router


SYSTEM_PROMPT = """You write pytest test cases for code changes.

You will receive a unified diff showing a code fix. Write pytest tests that:
1. Verify the fix actually resolves the bug (positive cases)
2. Cover edge cases (empty inputs, None, boundary conditions)
3. Use pytest fixtures and parametrize where appropriate

Rules:
- Output ONLY valid Python code, no markdown fences, no explanation
- Start with necessary imports
- Use descriptive test function names: test_<scenario>_<expected_outcome>
- Include at least 3 test cases
- Tests must be runnable with: pytest <filename>.py"""


class TestWriterAgent(BaseAgent):
    name = "test_writer"

    async def run(self, state: dict) -> dict:
        analysis = state.get("issue_analysis", {})
        diff = state.get("proposed_diff", "")

        user_message = f"""Bug description:
{analysis.get('actual_behavior', '')}

Expected behavior:
{analysis.get('expected_behavior', '')}

Proposed fix (unified diff):
{diff}

Write pytest tests."""

        test_code = await llm_router.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            task="reasoning",
        )

        return {
            "test_code": test_code.strip(),
            "events": [{
                "agent": self.name,
                "type": "completed",
                "summary": f"Generated test file ({len(test_code)} chars)",
            }],
        }


test_writer = TestWriterAgent()