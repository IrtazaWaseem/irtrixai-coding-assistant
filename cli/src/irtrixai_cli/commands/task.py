import contextlib

import typer

from irtrixai_cli.client import (
    ApprovalStateError,
    CLIError,
    ConflictError,
    IrtrixClient,
)
from irtrixai_cli.output import (
    print_error,
    print_info,
    print_success,
    print_warning,
    render_events,
    render_execution,
    render_task,
)


def create_task_command(
    ctx: typer.Context,
    workspace: str = typer.Option(..., "--workspace", "-w", help="Target workspace root path"),
    prompt: str = typer.Option(..., "--prompt", "-p", help="Task specification and instructions"),
) -> None:
    """Creates a new agent coding task."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            task = client.create_task(workspace_path=workspace, prompt=prompt)
            print_success(f"Task created successfully. ID: [bold cyan]{task.id}[/bold cyan]")
            render_task(task, title="Created Task")
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err


def status_task_command(ctx: typer.Context, task_id: str = typer.Argument(..., help="Task UUID")) -> None:
    """Fetches the authoritative status of a task."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            task = client.get_task(task_id)
            render_task(task, title="Authoritative Task Status")
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err


def run_task_command(ctx: typer.Context, task_id: str = typer.Argument(..., help="Task UUID")) -> None:
    """Triggers or resumes task execution via POST /api/v1/tasks/{id}/run."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            exec_res = client.run_task(task_id)
            render_execution(exec_res)

            if exec_res.status == "awaiting_approval":
                print_warning("Execution paused at Human Approval Gate.")
                print_info(f"Run 'irtrixai task approve {task_id}' or 'irtrixai task reject {task_id}' to proceed.")
            elif exec_res.status == "completed":
                print_success("Task execution completed.")
            elif exec_res.status in ("failed", "aborted"):
                raise typer.Exit(code=1)
        except ConflictError as err:
            print_error(f"Conflict: {err.message}")
            with contextlib.suppress(CLIError):
                current_task = client.get_task(task_id)
                render_task(current_task, title="Current Task State")
            raise typer.Exit(code=4) from err
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err


def approve_task_command(ctx: typer.Context, task_id: str = typer.Argument(..., help="Task UUID")) -> None:
    """Submits human approval for a pending proposed patch."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            exec_res = client.submit_approval(task_id=task_id, approved=True)
            render_execution(exec_res)
            if exec_res.status == "completed":
                print_success("Task completed successfully.")
            elif exec_res.status in ("failed", "aborted"):
                raise typer.Exit(code=1)
        except ApprovalStateError as err:
            print_error(f"Approval rejected: {err.message}")
            with contextlib.suppress(CLIError):
                task = client.get_task(task_id)
                render_task(task, title="Reconciled Task State")
            raise typer.Exit(code=4) from err
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err


def reject_task_command(
    ctx: typer.Context,
    task_id: str = typer.Argument(..., help="Task UUID"),
    feedback: str = typer.Option(..., "--feedback", "-f", help="Rejection reason or guidance"),
) -> None:
    """Rejects proposed modifications and routes task to debugger or aborts."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            exec_res = client.submit_approval(task_id=task_id, approved=False, feedback=feedback)
            render_execution(exec_res)
        except ApprovalStateError as err:
            print_error(f"Rejection rejected: {err.message}")
            with contextlib.suppress(CLIError):
                task = client.get_task(task_id)
                render_task(task, title="Reconciled Task State")
            raise typer.Exit(code=4) from err
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err


def events_task_command(ctx: typer.Context, task_id: str = typer.Argument(..., help="Task UUID")) -> None:
    """Fetches and renders the one-shot persisted event snapshot."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            events = client.get_task_events(task_id)
            render_events(events)
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err