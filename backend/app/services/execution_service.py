import contextlib
import subprocess
import threading
import time
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import (
    AppException,
    ContainerExecutionException,
    ContainerTimeoutException,
)
from app.core.security import (
    resolve_safe_path,
    truncate_output,
    validate_command,
)


class ExecutionService:
    """Manages the deterministic lifecycle of ephemeral Docker sandbox containers."""

    @staticmethod
    def verify_docker_available() -> bool:
        """Checks if the Docker CLI and daemon are accessible."""
        try:
            proc = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=5,
            )
            return proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _create_container(
        self,
        argv: list[str],
        workspace_path: Path,
        image: str | None = None,
    ) -> str:
        """Creates an ephemeral container and returns its authoritative container ID."""
        target_image = image or settings.DOCKER_SANDBOX_IMAGE

        cmd = [
            "docker",
            "create",
            "--network=none",
            f"--user={settings.SANDBOX_CONTAINER_USER}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            f"--memory={settings.SANDBOX_MEMORY_LIMIT}",
            f"--cpus={settings.SANDBOX_CPU_LIMIT}",
            f"--pids-limit={settings.SANDBOX_PIDS_LIMIT}",
            "--read-only",
            f"--tmpfs=/tmp:rw,noexec,nosuid,size={settings.SANDBOX_TMPFS_SIZE}",
            "--workdir=/workspace",
            f"--volume={workspace_path!s}:/workspace:ro",
            "--env=PATH=/usr/local/bin:/usr/bin:/bin",
            "--env=TMPDIR=/tmp",
            "--env=TEMP=/tmp",
            "--env=TMP=/tmp",
            "--env=HOME=/tmp",
            "--env=PYTHONPYCACHEPREFIX=/tmp/pycache",
            "--env=RUFF_CACHE_DIR=/tmp/ruff_cache",
            "--env=PYTHONUNBUFFERED=1",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--env=LANG=C.UTF-8",
            "--env=LC_ALL=C.UTF-8",
            target_image,
            *argv,
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                shell=False,
            )
        except OSError as err:
            raise ContainerExecutionException(f"Failed to invoke Docker CLI: {err}") from err

        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip()
            raise ContainerExecutionException(f"Failed to create sandbox container: {err_msg}")

        container_id = proc.stdout.strip()
        if not container_id:
            raise ContainerExecutionException("Docker create produced an empty container ID.")

        return container_id

    def _start_container(self, container_id: str) -> None:
        """Starts the specified container by its authoritative container ID."""
        proc = subprocess.run(
            ["docker", "start", container_id],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or proc.stdout.strip()
            raise ContainerExecutionException(f"Failed to start sandbox container: {err_msg}")

    def _wait_container(
        self,
        container_id: str,
        timeout_seconds: int,
        command: str | None = None,
    ) -> int:
        """Waits for the container to terminate, enforcing host-bounded timeouts."""
        try:
            proc = subprocess.run(
                ["docker", "wait", container_id],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
            raw_exit = proc.stdout.strip()
            try:
                return int(raw_exit)
            except ValueError:
                return proc.returncode
        except subprocess.TimeoutExpired as err:
            self._kill_container(container_id)
            raise ContainerTimeoutException(
                timeout_seconds=timeout_seconds,
                command=command,
                details={"container_id": container_id[:12]},
            ) from err

    @staticmethod
    def _collect_bounded_logs(
        container_id: str,
        max_bytes: int = settings.MAX_TOOL_OUTPUT_BYTES,
    ) -> tuple[str, str, bool]:
        """Streams container logs up to buffer threshold directly from Docker."""
        buffer_cap = max_bytes + 4096
        cmd = ["docker", "logs", container_id]

        stdout_bytes = bytearray()
        stderr_bytes = bytearray()
        was_capped = [False]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except OSError as err:
            return "", f"Failed to retrieve logs: {err}", False

        def _reader(stream, out_buf: bytearray) -> None:
            if stream is None:
                return
            with contextlib.suppress(OSError, ValueError):
                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        break
                    if len(out_buf) < buffer_cap:
                        needed = buffer_cap - len(out_buf)
                        out_buf.extend(chunk[:needed])
                    if len(out_buf) >= buffer_cap:
                        was_capped[0] = True
                        break

        err_thread = threading.Thread(target=_reader, args=(proc.stderr, stderr_bytes), daemon=True)
        err_thread.start()

        _reader(proc.stdout, stdout_bytes)

        with contextlib.suppress(Exception):
            proc.kill()

        err_thread.join(timeout=2)
        with contextlib.suppress(Exception):
            proc.wait(timeout=2)

        decoded_stdout = stdout_bytes.decode("utf-8", errors="replace")
        decoded_stderr = stderr_bytes.decode("utf-8", errors="replace")

        sanitized_stdout, tr_out = truncate_output(decoded_stdout, max_bytes=max_bytes)
        sanitized_stderr, tr_err = truncate_output(decoded_stderr, max_bytes=max_bytes)

        is_truncated = was_capped[0] or tr_out or tr_err
        return sanitized_stdout, sanitized_stderr, is_truncated

    @staticmethod
    def _kill_container(container_id: str) -> None:
        """Kills a running container by its authoritative ID."""
        with contextlib.suppress(Exception):
            subprocess.run(
                ["docker", "kill", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=5,
            )

    @staticmethod
    def _cleanup_container(container_id: str) -> None:
        """Guarantees container termination and removal across all failure modes."""
        with contextlib.suppress(Exception):
            subprocess.run(
                ["docker", "kill", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=5,
            )

        with contextlib.suppress(Exception):
            subprocess.run(
                ["docker", "rm", "-f", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
                timeout=5,
            )

    def execute_in_sandbox(
        self,
        command: str | list[str],
        workspace_path: str | Path,
        timeout_seconds: int,
        image: str | None = None,
        trusted_base: str | Path | None = None,
    ) -> dict:
        """Coordinates full container lifecycle for command execution."""
        # 1. Workspace validation boundary
        if not workspace_path:
            raise AppException("Workspace path cannot be empty.", status_code=400)

        raw_path = Path(workspace_path)
        if trusted_base is not None:
            validated_workspace = resolve_safe_path(trusted_base, raw_path)
        else:
            try:
                validated_workspace = raw_path.resolve(strict=True)
            except (FileNotFoundError, OSError) as err:
                raise AppException(
                    f"Workspace directory does not exist: '{workspace_path}'",
                    status_code=404,
                    details={"workspace_path": str(workspace_path)},
                ) from err

        if not validated_workspace.exists():
            raise AppException(
                f"Workspace directory does not exist: '{workspace_path}'",
                status_code=404,
                details={"workspace_path": str(workspace_path)},
            )

        if not validated_workspace.is_dir():
            raise AppException(
                f"Workspace path is not a directory: '{workspace_path}'",
                status_code=400,
                details={"workspace_path": str(workspace_path)},
            )

        # 2. Command validation boundary
        validated_argv = validate_command(command)

        # 3. Docker execution
        container_id: str | None = None
        start_time = time.perf_counter()

        try:
            container_id = self._create_container(
                argv=validated_argv,
                workspace_path=validated_workspace,
                image=image,
            )
            self._start_container(container_id)
            exit_code = self._wait_container(
                container_id=container_id,
                timeout_seconds=timeout_seconds,
                command=" ".join(validated_argv),
            )
            stdout, stderr, is_truncated = self._collect_bounded_logs(
                container_id, max_bytes=settings.MAX_TOOL_OUTPUT_BYTES
            )
            duration = time.perf_counter() - start_time

            return {
                "command": " ".join(validated_argv),
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "truncated": is_truncated,
                "duration_seconds": round(duration, 3),
            }
        finally:
            if container_id:
                self._cleanup_container(container_id)
