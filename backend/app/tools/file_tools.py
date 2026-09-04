import contextlib
import fnmatch
import os
import re
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.constants import IGNORED_DIRECTORIES, IGNORED_FILES, is_protected_file
from app.core.exceptions import (
    AppException,
    EntityNotFoundException,
    SecurityViolationException,
    ToolExecutionException,
)
from app.tools.base import ToolResult
from app.tools.schemas import (
    ApplyPatchOutput,
    FileEntry,
    ListFilesOutput,
    ReadFileOutput,
    SearchCodeOutput,
    SearchMatch,
    WriteFileOutput,
)
from app.tools.validators import (
    truncate_output,
    validate_content_size,
    validate_file_size,
    validate_not_protected,
    validate_safe_path,
    validate_workspace_dir,
)

MAX_LIST_ENTRIES = 500


def _handle_tool_error(
    tool_name: str,
    exc: Exception,
    raise_on_error: bool,
    metadata: dict | None = None,
) -> ToolResult:
    if raise_on_error:
        raise exc
    meta = metadata or {}
    meta["error_type"] = type(exc).__name__
    if hasattr(exc, "details"):
        meta["details"] = exc.details
    return ToolResult.fail(tool_name=tool_name, error=str(exc), metadata=meta)


def list_files(
    relative_directory: str = ".",
    recursive: bool = False,
    max_depth: int = 2,
    workspace_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Lists files and directories recursively within workspace boundary."""
    try:
        if max_depth < 1:
            raise ToolExecutionException("max_depth must be at least 1.")

        base_dir = validate_workspace_dir(workspace_root)
        target_dir = validate_safe_path(base_dir, relative_directory, must_exist=True)

        if not target_dir.is_dir():
            raise ToolExecutionException(f"Path '{relative_directory}' is not a directory.")

        effective_max_depth = max_depth if recursive else 1
        entries: list[FileEntry] = []
        truncated = False

        def _walk(current: Path, depth: int):
            nonlocal truncated
            if depth > effective_max_depth or len(entries) >= MAX_LIST_ENTRIES:
                if len(entries) >= MAX_LIST_ENTRIES:
                    truncated = True
                return

            try:
                scanned = sorted(
                    os.scandir(current),
                    key=lambda e: (not e.is_dir(), e.name.lower()),
                )
            except OSError:
                return

            for item in scanned:
                if len(entries) >= MAX_LIST_ENTRIES:
                    truncated = True
                    break

                if (
                    item.name in IGNORED_DIRECTORIES
                    or item.name in IGNORED_FILES
                    or is_protected_file(item.name)
                ):
                    continue

                try:
                    safe_child = validate_safe_path(base_dir, item.path, must_exist=False)
                    if is_protected_file(safe_child):
                        continue
                except SecurityViolationException:
                    # Robust symlink handling: skip unsafe entries without aborting listing
                    continue

                rel_path = str(safe_child.relative_to(base_dir)).replace("\\", "/")

                if item.is_dir(follow_symlinks=False):
                    entries.append(FileEntry(name=item.name, path=rel_path, type="directory"))
                    if recursive and depth < effective_max_depth:
                        _walk(safe_child, depth + 1)
                elif item.is_file(follow_symlinks=False):
                    size = None
                    with contextlib.suppress(OSError):
                        size = item.stat().st_size
                    entries.append(FileEntry(name=item.name, path=rel_path, type="file", size=size))

        _walk(target_dir, depth=1)

        result_data = ListFilesOutput(
            entries=entries,
            total_entries=len(entries),
            truncated=truncated,
        )
        return ToolResult.ok(tool_name="list_files", output=result_data.model_dump())
    except Exception as err:  # noqa: BLE001
        return _handle_tool_error("list_files", err, raise_on_error)


def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    workspace_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Reads a text file with line range pagination, binary detection, and size limits."""
    try:
        base_dir = validate_workspace_dir(workspace_root)
        safe_file = validate_safe_path(base_dir, path, must_exist=True)
        validate_not_protected(path, safe_file)

        if safe_file.is_dir():
            raise ToolExecutionException(f"Path '{path}' is a directory, not a file.")

        validate_file_size(safe_file)

        with safe_file.open("rb") as f:
            header = f.read(8192)
            if b"\x00" in header:
                raise ToolExecutionException(f"Cannot read binary file '{path}' as text.")

        try:
            raw_text = safe_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as err:
            raise ToolExecutionException(f"File '{path}' is not valid UTF-8 text: {err}") from err

        all_lines = raw_text.splitlines()
        total_lines = len(all_lines)
        rel_path = str(safe_file.relative_to(base_dir)).replace("\\", "/")

        if total_lines == 0:
            result_data = ReadFileOutput(
                path=rel_path,
                content="",
                start_line=0,
                end_line=0,
                total_lines=0,
                truncated=False,
                has_more=False,
            )
            return ToolResult.ok(tool_name="read_file", output=result_data.model_dump())

        if start_line is not None and start_line < 1:
            raise ToolExecutionException(f"start_line ({start_line}) must be >= 1.")
        if end_line is not None and end_line < 1:
            raise ToolExecutionException(f"end_line ({end_line}) must be >= 1.")
        if start_line is not None and end_line is not None and start_line > end_line:
            raise ToolExecutionException(
                f"start_line ({start_line}) cannot be greater than end_line ({end_line})."
            )

        start_idx = (start_line - 1) if start_line is not None else 0
        end_idx = end_line if end_line is not None else total_lines

        start_idx = max(0, min(start_idx, total_lines))
        end_idx = max(start_idx, min(end_idx, total_lines))

        sliced_lines = all_lines[start_idx:end_idx]
        sliced_content = "\n".join(sliced_lines)
        final_content, was_truncated = truncate_output(sliced_content)

        result_data = ReadFileOutput(
            path=rel_path,
            content=final_content,
            start_line=start_idx + 1 if total_lines > 0 else 0,
            end_line=end_idx,
            total_lines=total_lines,
            truncated=was_truncated,
            has_more=(end_idx < total_lines) or was_truncated,
        )
        return ToolResult.ok(tool_name="read_file", output=result_data.model_dump())
    except Exception as err:  # noqa: BLE001
        return _handle_tool_error("read_file", err, raise_on_error)


def search_code(
    query: str,
    relative_path: str = ".",
    file_pattern: str | None = None,
    workspace_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Performs deterministic case-insensitive literal substring code search."""
    try:
        if not query:
            raise ToolExecutionException("Search query cannot be empty.")

        base_dir = validate_workspace_dir(workspace_root)
        target_dir = validate_safe_path(base_dir, relative_path, must_exist=True)

        if not target_dir.is_dir():
            raise ToolExecutionException(f"Search path '{relative_path}' is not a directory.")

        max_matches = settings.MAX_SEARCH_RESULTS
        max_file_size = settings.MAX_SEARCH_FILE_SIZE

        query_lower = query.lower()
        matches: list[SearchMatch] = []
        truncated = False

        for root, dirs, files in os.walk(target_dir):
            dirs[:] = sorted([d for d in dirs if d not in IGNORED_DIRECTORIES])
            files.sort()

            for file in files:
                if len(matches) >= max_matches:
                    truncated = True
                    break

                if file in IGNORED_FILES or is_protected_file(file):
                    continue

                if file_pattern and not fnmatch.fnmatch(file, file_pattern):
                    continue

                raw_file_path = Path(root) / file

                try:
                    safe_file = validate_safe_path(base_dir, raw_file_path, must_exist=True)
                except (SecurityViolationException, EntityNotFoundException, AppException):
                    continue

                if is_protected_file(safe_file):
                    continue

                if not safe_file.is_file():
                    continue

                rel_path = str(safe_file.relative_to(base_dir)).replace("\\", "/")

                try:
                    if safe_file.stat().st_size > max_file_size:
                        continue
                    with safe_file.open("rb") as f:
                        if b"\x00" in f.read(2048):
                            continue
                    file_text = safe_file.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue

                for line_idx, line in enumerate(file_text.splitlines(), start=1):
                    if query_lower in line.lower():
                        matches.append(
                            SearchMatch(
                                file_path=rel_path,
                                line_number=line_idx,
                                line_content=line[:250].strip(),
                            )
                        )
                        if len(matches) >= max_matches:
                            truncated = True
                            break

            if truncated:
                break

        result_data = SearchCodeOutput(
            query=query,
            matches=matches,
            total_matches=len(matches),
            truncated=truncated,
        )
        return ToolResult.ok(tool_name="search_code", output=result_data.model_dump())
    except Exception as err:  # noqa: BLE001
        return _handle_tool_error("search_code", err, raise_on_error)


def write_file(
    path: str,
    content: str,
    workspace_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Performs an atomic write to a target file within workspace boundaries."""
    try:
        base_dir = validate_workspace_dir(workspace_root)
        safe_file = validate_safe_path(base_dir, path, must_exist=False)
        validate_not_protected(path, safe_file)

        if safe_file.exists() and safe_file.is_dir():
            raise ToolExecutionException(
                f"Cannot write to path '{path}': it is an existing directory."
            )

        byte_length = validate_content_size(
            content, max_bytes=settings.MAX_READ_FILE_BYTES, field_name="content"
        )

        safe_file.parent.mkdir(parents=True, exist_ok=True)
        is_new = not safe_file.exists()

        temp_file = safe_file.parent / f".tmp_{uuid.uuid4().hex}"
        try:
            temp_file.write_text(content, encoding="utf-8")

            # TOCTOU mitigation: Re-verify boundary containment and target identity
            rechecked_path = validate_safe_path(base_dir, path, must_exist=False)
            if rechecked_path.resolve() != safe_file.resolve():
                raise ToolExecutionException(
                    f"Path target changed concurrently during write for '{path}'."
                )
            validate_not_protected(path, rechecked_path)

            temp_file.replace(safe_file)
        finally:
            if temp_file.exists():
                with contextlib.suppress(OSError):
                    temp_file.unlink()

        result_data = WriteFileOutput(
            path=str(safe_file.relative_to(base_dir)).replace("\\", "/"),
            bytes_written=byte_length,
            is_new_file=is_new,
        )
        return ToolResult.ok(tool_name="write_file", output=result_data.model_dump())
    except Exception as err:  # noqa: BLE001
        return _handle_tool_error("write_file", err, raise_on_error)


def apply_patch(
    path: str,
    patch_content: str,
    workspace_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> ToolResult:
    """Applies unified diff hunks or search-and-replace blocks atomically."""
    try:
        base_dir = validate_workspace_dir(workspace_root)
        safe_file = validate_safe_path(base_dir, path, must_exist=True)
        validate_not_protected(path, safe_file)

        if safe_file.is_dir():
            raise ToolExecutionException(f"Path '{path}' is a directory, not a file.")

        validate_content_size(
            patch_content, max_bytes=settings.MAX_PATCH_SIZE, field_name="patch_content"
        )

        original_content = safe_file.read_text(encoding="utf-8")
        hunks_applied = 0
        new_content = original_content

        newline = "\r\n" if "\r\n" in original_content else "\n"
        ends_with_newline = original_content.endswith(("\n", "\r\n"))

        # Strategy 1: Search-and-replace block format
        if "<<<<<<< SEARCH" in patch_content and ">>>>>>> REPLACE" in patch_content:
            block_pattern = re.compile(
                r"<<<<<<< SEARCH\r?\n(.*?)\r?\n=======\r?\n(.*?)\r?\n>>>>>>> REPLACE",
                re.DOTALL,
            )
            matches = list(block_pattern.finditer(patch_content))
            if not matches:
                raise ToolExecutionException("Malformed search-and-replace patch structure.")

            current_text = original_content
            for idx, match in enumerate(matches, start=1):
                search_block, replace_block = match.group(1), match.group(2)
                if search_block not in current_text:
                    raise ToolExecutionException(
                        f"Search block {idx} context mismatch: target text not found in file."
                    )
                current_text = current_text.replace(search_block, replace_block, 1)
                hunks_applied += 1
            new_content = current_text

        # Strategy 2: Unified diff hunk format
        elif "@@" in patch_content:
            patch_lines = patch_content.splitlines()
            orig_lines = original_content.splitlines()
            hunk_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

            line_cursor = 0
            res_lines: list[str] = []
            hunk_lines: list[str] = []
            parsing_hunk = False

            def _commit_hunk(hlines: list[str]) -> None:
                nonlocal line_cursor, hunks_applied
                expected_context: list[str] = []
                replacement: list[str] = []
                for hl in hlines:
                    if hl.startswith(" "):
                        expected_context.append(hl[1:])
                        replacement.append(hl[1:])
                    elif hl.startswith("-"):
                        expected_context.append(hl[1:])
                    elif hl.startswith("+"):
                        replacement.append(hl[1:])

                block_len = len(expected_context)
                matched_idx = -1
                for idx in range(line_cursor, len(orig_lines) - block_len + 1):
                    if orig_lines[idx : idx + block_len] == expected_context:
                        matched_idx = idx
                        break

                if matched_idx == -1:
                    raise ToolExecutionException(
                        "Unified diff hunk context failed to match target file."
                    )

                res_lines.extend(orig_lines[line_cursor:matched_idx])
                res_lines.extend(replacement)
                line_cursor = matched_idx + block_len
                hunks_applied += 1

            for pl in patch_lines:
                if hunk_re.match(pl):
                    if parsing_hunk:
                        _commit_hunk(hunk_lines)
                        hunk_lines = []
                    parsing_hunk = True
                elif parsing_hunk:
                    if pl.startswith((" ", "-", "+")):
                        hunk_lines.append(pl)
                    elif pl.startswith("\\ No newline"):
                        continue

            if parsing_hunk and hunk_lines:
                _commit_hunk(hunk_lines)

            res_lines.extend(orig_lines[line_cursor:])
            new_content = newline.join(res_lines) + (newline if ends_with_newline else "")
        else:
            raise ToolExecutionException(
                "Unrecognized patch format. Provide unified diff (@@) or search-replace blocks."
            )

        if hunks_applied == 0:
            raise ToolExecutionException("No applicable hunks found in patch.")

        temp_file = safe_file.parent / f".tmp_{uuid.uuid4().hex}"
        try:
            temp_file.write_text(new_content, encoding="utf-8")

            # TOCTOU mitigation: Re-verify boundary containment and target identity
            rechecked_path = validate_safe_path(base_dir, path, must_exist=True)
            if rechecked_path.resolve() != safe_file.resolve():
                raise ToolExecutionException(
                    f"Path target changed concurrently during patch application for '{path}'."
                )
            validate_not_protected(path, rechecked_path)

            temp_file.replace(safe_file)
        finally:
            if temp_file.exists():
                with contextlib.suppress(OSError):
                    temp_file.unlink()

        result_data = ApplyPatchOutput(
            path=str(safe_file.relative_to(base_dir)).replace("\\", "/"),
            hunks_applied=hunks_applied,
            bytes_written=len(new_content.encode("utf-8")),
            applied=True,
        )
        return ToolResult.ok(tool_name="apply_patch", output=result_data.model_dump())
    except Exception as err:  # noqa: BLE001
        return _handle_tool_error(
            "apply_patch", err, raise_on_error, metadata={"original_preserved": True}
        )
