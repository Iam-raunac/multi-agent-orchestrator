import re


def parse_pytest_output(output: str) -> dict:
    """Read counts from pytest's final terminal summary."""
    summary = next(
        (line for line in reversed(output.splitlines())
         if line.startswith("=") and re.search(r"\bin \d+(?:\.\d+)?s\b", line)),
        "",
    )

    def count(label: str) -> int:
        match = re.search(rf"\b(\d+) {label}\b", summary)
        return int(match[1]) if match else 0

    passed, failed, errors = count("passed"), count("failed"), count("errors?")
    return {
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "total": passed + failed + errors,
        "failures": [line for line in output.splitlines() if line.startswith(("FAILED ", "ERROR "))],
    }
