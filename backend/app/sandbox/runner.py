from app.sandbox.executor import sandbox
from app.sandbox.parser import parse_pytest_output


async def run_tests(test_code: str, source_files: dict[str, str] | None = None) -> dict:
    """Run pytest on the given test code inside the Docker sandbox.

    Args:
        test_code: The pytest file content (from TestWriter agent).
        source_files: Optional dict of {path: content} for any code files the tests need.

    Returns:
        {tests_passed: bool, output: str, summary: dict}
    """
    files = {"test_fix.py": test_code}
    if source_files:
        files.update(source_files)

    # Install pytest first, then run it (the slim image doesn't include it)
    result = await sandbox.run_command(
        command=[
            "sh", "-c",
            "pip install pytest --quiet && pytest test_fix.py -v --tb=short",
        ],
        files=files,
    )

    parsed = parse_pytest_output(result["output"])

    return {
        "tests_passed": result["exit_code"] == 0 and parsed["failed"] == 0,
        "output": result["output"],
        "summary": parsed,
    }