from pathlib import Path

from app.sandbox.executor import sandbox
from app.sandbox.parser import parse_pytest_output

SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "node_modules"}


def _read_repo_files(repo_path: str | Path) -> dict[str, str]:
    root = Path(repo_path).resolve()
    files = {}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if SKIP_DIRS.intersection(rel.parts) or path.is_symlink():
            continue
        try:
            files[rel.as_posix()] = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
    return files


async def run_tests(
    test_code: str,
    repo_path: str | Path | None = None,
    diff: str | None = None,
) -> dict:
    """Apply one candidate to fresh source and validate the resulting code."""
    files = _read_repo_files(repo_path) if repo_path is not None else {}
    files["test_fix.py"] = test_code
    if diff:
        files.update({"patch.diff": diff.rstrip("\n") + "\n"})
    commands = [
        "git apply --whitespace=nowarn patch.diff || exit 10" if diff else "",
        "python -m pytest test_fix.py -v --tb=short",
    ]
    result = await sandbox.run_command(
        command=["sh", "-c", "\n".join(filter(None, commands))], files=files,
    )
    summary = parse_pytest_output(result["output"])
    exit_code = result["exit_code"]
    return {
        "tests_passed": (
            exit_code == 0 and not result.get("timed_out", False)
            and summary["passed"] > 0 and summary["failed"] == 0 and summary["errors"] == 0
        ),
        "output": result["output"],
        "summary": summary,
        "exit_code": exit_code,
    }
