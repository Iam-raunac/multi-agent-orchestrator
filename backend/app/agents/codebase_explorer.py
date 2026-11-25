from app.agents.base import BaseAgent
from app.rag.retriever import retriever


class CodebaseExplorerAgent(BaseAgent):
    name = "codebase_explorer"

    async def run(self, state: dict) -> dict:
        candidates = state.get("recovery_candidates", [])
        if candidates:
            recovered = "\n\n".join(
                f"# Recovered: {item['file_path']} (lines {item['start_line']}-{item['end_line']})"
                f"\n{item['content']}" for item in candidates
            )
            return {
                "code_context": f"{state.get('code_context', '')}\n\n{recovered}".strip(),
                "relevant_files": state.get("relevant_files", []) + [
                    {k: item[k] for k in ("file_path", "start_line", "end_line")}
                    for item in candidates
                ],
                "recovered_context": state.get("recovered_context", []) + candidates,
                "recovery_candidates": [],
                "events": [{
                    "agent": self.name, "type": "completed",
                    "summary": "Recovered " + ", ".join(
                        f"{item['file_path']}:{item['start_line']}-{item['end_line']} ({item['symbol']})"
                        for item in candidates
                    ),
                }],
            }

        analysis = state.get("issue_analysis", {})
        repo = state["repo_full_name"]

        # Combine module name + keywords into a single search query
        keywords = analysis.get("keywords", [])
        module = analysis.get("module", "")
        query = f"{module} {' '.join(keywords)}".strip()

        if not query:
            query = state.get("issue_title", "")

        # Pull top 5 most relevant code chunks from ChromaDB
        results = retriever.search(repo=repo, query=query, top_k=5)

        # Build a compact context string the FixDrafter can use as a prompt
        code_context = "\n\n".join([
            f"# File: {r['file_path']} (lines {r['start_line']}-{r['end_line']})\n{r['content']}"
            for r in results
        ])

        return {
            "relevant_files": [
                {"file_path": r["file_path"], "start_line": r["start_line"], "end_line": r["end_line"]}
                for r in results
            ],
            "code_context": code_context,
            "events": [{
                "agent": self.name,
                "type": "completed",
                "summary": f"Found {len(results)} relevant code chunks",
            }],
        }


codebase_explorer = CodebaseExplorerAgent()