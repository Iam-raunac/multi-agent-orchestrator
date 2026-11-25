"""Select missing Python source using a failed test's repository frames."""
import ast
import re
from pathlib import Path

MAX_CHUNKS = 3
MAX_CHARS = 6000
FRAME = re.compile(
    r'^\s*(?:File "([^"]+)", line (\d{1,7})|((?:/sandbox/)?[\w./-]+\.py):(\d{1,7}):)',
    re.MULTILINE,
)


def workspace_for(state: dict) -> Path:
    name = state["repo_full_name"].rsplit("/", 1)[-1]
    if not re.fullmatch(r"[\w.-]+", name) or name in {".", ".."}:
        raise ValueError("Invalid repository name")
    return Path("/tmp") / name


def relative_source(path: str, root: Path) -> str | None:
    path = path.removeprefix("/sandbox/")
    candidate = Path(path)
    try:
        resolved = (root / candidate).resolve()
        rel = resolved.relative_to(root.resolve())
    except (ValueError, OSError, RuntimeError):
        return None
    if not resolved.is_file() or rel.suffix != ".py":
        return None
    if any(part.startswith(".") or part in {"tests", "venv", "site-packages"} for part in rel.parts):
        return None
    if rel.name.startswith("test_") or rel.name.endswith("_test.py"):
        return None
    return rel.as_posix()


def _source_span(path: Path, line: int) -> tuple[int, int, str, str] | None:
    try:
        if path.stat().st_size > 256_000:
            return None
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, UnicodeError, SyntaxError, RecursionError):
        return None
    lines = source.splitlines()
    if not 1 <= line <= len(lines):
        return None
    blocks = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.lineno <= line <= (node.end_lineno or node.lineno)
    ]
    if blocks:
        chosen = min(blocks, key=lambda node: (node.end_lineno or node.lineno) - node.lineno)
        start, end = chosen.lineno, chosen.end_lineno or chosen.lineno
        symbol = chosen.name
    else:
        start, end, symbol = line - 3, line + 3, "<module>"
    start, end = max(1, start, line - 20), min(len(lines), end, line + 20)
    return start, end, symbol, "\n".join(lines[start - 1:end])


def missing_context(state: dict, root: Path) -> list[dict]:
    """Return source snippets only for supported runtime test failures."""
    if state.get("failure_stage") != "sandbox" or state.get("sandbox_exit_code") != 1:
        return []
    known = {}
    for item in state.get("relevant_files", []):
        path = relative_source(item["file_path"], root)
        if path:
            known.setdefault(path, []).append((item["start_line"], item["end_line"]))

    chunks = []
    remaining = MAX_CHARS - sum(len(item.get("content", "")) for item in state.get("recovered_context", []))
    for frame in reversed(list(FRAME.finditer(state.get("test_output", "")[-16000:]))):
        path = relative_source(frame[1] or frame[3], root)
        line = int(frame[2] or frame[4])
        if path is None or any(start <= line <= end for start, end in known.get(path, [])):
            continue
        span = _source_span(root / path, line)
        if span is None:
            continue
        start, end, symbol, snippet = span
        if not snippet or len(snippet) > remaining:
            continue
        chunks.append({
            "file_path": path, "start_line": start, "end_line": end,
            "symbol": symbol, "content": snippet,
        })
        known.setdefault(path, []).append((start, end))
        remaining -= len(snippet)
        if len(chunks) == MAX_CHUNKS:
            break
    return chunks
