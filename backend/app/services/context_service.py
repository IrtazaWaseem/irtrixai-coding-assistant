import logging
import re
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.schemas.agent_contracts import RelevantFileContext, RepositoryContext
from app.tools.file_tools import list_files, read_file, search_code
from app.tools.validators import (
    is_protected_file,
    truncate_output,
    validate_safe_path,
)

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "a",
    "an",
    "the",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "and",
    "or",
    "is",
    "are",
    "was",
    "were",
    "it",
    "this",
    "that",
    "be",
    "with",
    "as",
    "by",
    "from",
    "into",
    "all",
    "please",
    "can",
    "you",
    "should",
    "would",
    "could",
    "do",
    "does",
    "did",
    "have",
    "has",
    "had",
    "will",
    "shall",
    "may",
    "might",
    "must",
    "need",
    "want",
    "like",
    "using",
    "use",
}

CODE_EXTENSIONS = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".java",
    ".toml",
    ".json",
    ".yaml",
    ".yml",
    ".md",
    ".sql",
    ".sh",
    ".txt",
}


def extract_file_paths(tool_res: Any) -> list[str]:
    """Extracts a clean flat list of relative file paths from list_files ToolResult payloads."""
    raw_list: list[Any] = []

    if hasattr(tool_res, "output") and tool_res.output is not None:
        out = tool_res.output
        if isinstance(out, dict):
            for key in ("files", "entries", "items", "paths"):
                if key in out and isinstance(out[key], (list, tuple)):
                    raw_list = list(out[key])
                    break
        elif isinstance(out, (list, tuple)):
            raw_list = list(out)
        elif isinstance(out, str):
            raw_list = [line.strip() for line in out.splitlines() if line.strip()]

    if (
        not raw_list
        and hasattr(tool_res, "metadata")
        and isinstance(tool_res.metadata, dict)
    ):
        for key in ("files", "entries", "items", "paths"):
            if key in tool_res.metadata and isinstance(
                tool_res.metadata[key], (list, tuple)
            ):
                raw_list = list(tool_res.metadata[key])
                break

    files: list[str] = []
    for item in raw_list:
        if isinstance(item, str):
            files.append(item)
        elif isinstance(item, dict):
            val = item.get("path") or item.get("name") or item.get("file")
            if val:
                files.append(str(val))
    return files


def extract_task_keywords(prompt: str) -> list[str]:
    """Extracts significant identifiers, file references, and terms from task prompt."""
    if not prompt or not prompt.strip():
        return []

    file_pattern = re.compile(r"[A-Za-z0-9_\-\.\/]+\.[a-zA-Z0-9]+", re.IGNORECASE)
    file_tokens = file_pattern.findall(prompt)

    word_pattern = re.compile(r"[A-Za-z_][A-Za-z0-9_\-]*", re.IGNORECASE)
    raw_words = word_pattern.findall(prompt)

    keywords: list[str] = []

    for ft in file_tokens:
        clean_ft = ft.strip().lower()
        if clean_ft and clean_ft not in keywords:
            keywords.append(clean_ft)

    for w in raw_words:
        clean_w = w.strip().lower()
        if len(clean_w) >= 3 and clean_w not in STOP_WORDS and clean_w not in keywords:
            keywords.append(clean_w)

    return keywords[:10]


def build_repository_context(
    workspace_path: str,
    task_prompt: str,
    workspace_summary: str | None = None,
    tech_stack: list[str] | None = None,
    max_files: int | None = None,
    max_file_bytes: int | None = None,
    max_total_bytes: int | None = None,
    max_excerpt_lines: int | None = None,
    max_search_results: int | None = None,
) -> RepositoryContext:
    """Deterministically assembles bounded repository context without using LLM retrieval."""
    max_files = max_files or getattr(settings, "MAX_CONTEXT_FILES", 6)
    max_file_bytes = max_file_bytes or getattr(
        settings, "MAX_FILE_CONTEXT_BYTES", 8_000
    )
    max_total_bytes = max_total_bytes or getattr(
        settings, "MAX_TOTAL_CONTEXT_BYTES", 30_000
    )
    max_excerpt_lines = max_excerpt_lines or getattr(settings, "MAX_EXCERPT_LINES", 80)
    max_search_results = max_search_results or getattr(
        settings, "MAX_SEARCH_RESULTS", 15
    )

    tech_stack = tech_stack or ["python"]

    ws_obj = Path(workspace_path)
    if not workspace_path or not ws_obj.is_dir():
        logger.warning(
            "Repository context cannot inspect non-existent workspace: '%s'",
            workspace_path,
        )
        return RepositoryContext(
            summary=(
                workspace_summary
                or f"Workspace root at {workspace_path} (unavailable)."
            ),
            tech_stack=tech_stack,
            total_files_considered=0,
            files_included=0,
            truncated=False,
            total_context_bytes=0,
        )

    resolved_ws = ws_obj.resolve()

    # 1. Authoritative file inventory via safe tool using clean path extractor
    list_res = list_files(recursive=True, workspace_root=resolved_ws)
    raw_files = extract_file_paths(list_res)
    total_considered = len(raw_files)

    eligible_files: list[str] = []
    for f in raw_files:
        norm_f = f.replace("\\", "/").strip()
        if norm_f.startswith("./"):
            norm_f = norm_f[2:]
        if norm_f.startswith("/"):
            norm_f = norm_f[1:]
        if not norm_f or is_protected_file(norm_f):
            continue
        suffix = Path(norm_f).suffix.lower()
        name = Path(norm_f).name.lower()
        if (
            suffix in CODE_EXTENSIONS
            or name
            in (
                "pyproject.toml",
                "package.json",
                "cargo.toml",
                "go.mod",
                "dockerfile",
            )
            or name.startswith("dockerfile")
        ):
            eligible_files.append(norm_f)

    keywords = extract_task_keywords(task_prompt)

    # 2. Content search matches for top keywords
    search_match_map: dict[str, list[int]] = {}
    search_keywords = [
        k for k in keywords if not k.endswith((".py", ".ts", ".js", ".json"))
    ][:4]

    for sk in search_keywords:
        try:
            safe_pattern = re.escape(sk)
            s_res = search_code(
                pattern=safe_pattern,
                max_results=max_search_results,
                workspace_root=resolved_ws,
            )
            if s_res.success and s_res.output and isinstance(s_res.output, dict):
                matches = s_res.output.get("matches", [])
                if isinstance(matches, list):
                    for m in matches:
                        if isinstance(m, dict) and "file" in m and "line" in m:
                            mf = str(m["file"]).replace("\\", "/").strip()
                            if mf.startswith("./"):
                                mf = mf[2:]
                            search_match_map.setdefault(mf, []).append(int(m["line"]))
        except Exception as search_err:
            logger.debug(
                "Context search_code skipped for pattern '%s': %s", sk, search_err
            )

    # 3. Deterministic relevance scoring
    scored_files: list[tuple[float, str, list[str]]] = []
    prompt_lower = task_prompt.lower()

    for f in eligible_files:
        score = 0.0
        reasons: list[str] = []
        f_lower = f.lower()
        f_name = Path(f_lower).name
        f_stem = Path(f_lower).stem

        # A. Explicit path, filename, or component stem mention in user prompt
        if f_lower in prompt_lower or f_name in prompt_lower:
            score += 10.0
            reasons.append(f"Referenced directly in prompt ('{f_name}')")
        elif len(f_stem) >= 3 and f_stem in prompt_lower:
            score += 8.0
            reasons.append(f"Component stem referenced in prompt ('{f_stem}')")

        # B. Keyword match in path or filename
        for kw in keywords:
            if kw in f_name:
                score += 4.0
                reasons.append(f"Filename contains keyword '{kw}'")
            elif len(f_stem) >= 3 and kw in f_stem:
                score += 4.0
                reasons.append(f"Stem contains keyword '{kw}'")
            elif kw in f_lower:
                score += 1.5
                reasons.append(f"Path contains keyword '{kw}'")

        # C. Search content matches
        if f in search_match_map or f_name in search_match_map:
            matches = search_match_map.get(f) or search_match_map.get(f_name, [])
            match_cnt = len(matches)
            score += min(match_cnt * 2.0, 6.0)
            reasons.append(f"Contains {match_cnt} search match(es)")

        # D. Test / Source relationship
        is_test = (
            f_name.startswith("test_")
            or f_name.endswith(("_test.py", ".test.ts", ".spec.ts"))
            or "tests/" in f_lower
        )
        if is_test:
            base_target = f_name.replace("test_", "").replace("_test", "")
            for other in eligible_files:
                if other != f and (
                    base_target in other.lower()
                    or Path(other.lower()).stem in base_target
                ):
                    score += 3.0
                    reasons.append(f"Test file for component '{base_target}'")
                    break

        # E. Project manifest relevance
        if f_name in (
            "pyproject.toml",
            "package.json",
            "cargo.toml",
            "go.mod",
            "requirements.txt",
        ):
            score += 1.0
            reasons.append("Project configuration manifest")

        if score > 0.0:
            scored_files.append((score, f, reasons))

    scored_files.sort(key=lambda item: (-item[0], item[1]))

    # Deduplicate selected targets
    selected_ranked: list[tuple[float, str, list[str]]] = []
    seen_paths: set[str] = set()
    for sc, p, r in scored_files:
        if p not in seen_paths:
            seen_paths.add(p)
            selected_ranked.append((sc, p, r))
        if len(selected_ranked) >= max_files:
            break

    # 4. Gather bounded excerpts using safe read_file (positional path only)
    relevant_files: list[RelevantFileContext] = []
    total_context_bytes = 0
    overall_truncated = False

    for sc, p, reasons in selected_ranked:
        try:
            validate_safe_path(resolved_ws, p)
        except Exception:
            continue

        try:
            read_res = read_file(p, workspace_root=resolved_ws)
        except Exception as read_err:
            logger.debug("Read file skipped for '%s': %s", p, read_err)
            continue

        if not getattr(read_res, "success", False) or read_res.output is None:
            continue

        content = ""
        if isinstance(read_res.output, str):
            content = read_res.output
        elif isinstance(read_res.output, dict):
            content = str(
                read_res.output.get("content", read_res.output.get("text", ""))
            )
            if not content and "content" not in read_res.output:
                content = str(read_res.output)
        else:
            content = str(read_res.output)

        # Slice lines in Python to avoid keyword argument incompatibilities
        lines = content.splitlines()
        file_truncated = False
        if len(lines) > max_excerpt_lines:
            content = "\n".join(lines[:max_excerpt_lines])
            file_truncated = True

        content_bytes = len(content.encode("utf-8"))

        # Enforce per-file byte limit
        if content_bytes > max_file_bytes:
            trunc_raw = truncate_output(content, max_bytes=max_file_bytes)
            content = (
                trunc_raw[0] if isinstance(trunc_raw, (tuple, list)) else str(trunc_raw)
            )
            content_bytes = len(content.encode("utf-8"))
            file_truncated = True
            overall_truncated = True

        # Enforce total context byte limit
        if total_context_bytes + content_bytes > max_total_bytes:
            available = max(0, max_total_bytes - total_context_bytes)
            if available > 100:
                trunc_raw = truncate_output(content, max_bytes=available)
                content = (
                    trunc_raw[0]
                    if isinstance(trunc_raw, (tuple, list))
                    else str(trunc_raw)
                )
                content_bytes = len(content.encode("utf-8"))
                file_truncated = True
            else:
                overall_truncated = True
                break
            overall_truncated = True

        total_context_bytes += content_bytes
        lines_count = len(content.splitlines())

        relevant_files.append(
            RelevantFileContext(
                path=p,
                relevance_score=round(sc, 2),
                reason="; ".join(reasons) if reasons else "Keyword association",
                excerpt=content,
                start_line=1,
                end_line=max(1, lines_count),
                truncated=file_truncated,
            )
        )

        if total_context_bytes >= max_total_bytes:
            overall_truncated = True
            break

    summary_lines = [
        f"Evaluated {total_considered} workspace files; selected {len(relevant_files)} relevant file(s).",
        f"Tech stack: {', '.join(tech_stack)}.",
    ]
    if relevant_files:
        file_summary = ", ".join(
            f"{rf.path} (score: {rf.relevance_score})" for rf in relevant_files
        )
        summary_lines.append(f"Ranked context files: {file_summary}.")
    if overall_truncated:
        summary_lines.append("Context bounded by strict byte limits.")

    return RepositoryContext(
        summary=" ".join(summary_lines),
        tech_stack=tech_stack,
        relevant_files=relevant_files,
        total_files_considered=total_considered,
        files_included=len(relevant_files),
        truncated=overall_truncated,
        total_context_bytes=total_context_bytes,
    )
