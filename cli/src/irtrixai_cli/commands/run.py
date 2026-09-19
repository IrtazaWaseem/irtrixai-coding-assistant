import time

import typer
from rich.prompt import Confirm, Prompt

from irtrixai_cli.client import (
    ApprovalStateError,
    CLIError,
    ConflictError,
    IrtrixClient,
)
from irtrixai_cli.output import (
    console,
    print_error,
    print_info,
    print_success,
    print_warning,
    render_diff,
    render_final_result,
    render_task,
)


def run_composite_command(
    ctx: typer.Context,
    workspace: str = typer.Option(
        ..., "--workspace", "-w", help="Workspace absolute root directory"
    ),
    prompt: str = typer.Option(..., "--prompt", "-p", help="Task implementation prompt"),
) -> None:
    """Executes the full agent lifecycle: create, supervise, review, verify, and finalize."""
    api_url: str = ctx.obj["api_url"]

    with IrtrixClient(api_url) as client:
        try:
            print_info("Creating autonomous agent task...")
            task = client.create_task(workspace_path=workspace, prompt=prompt)
            task_id = task.id
            print_success(f"Task registered: [bold cyan]{task_id}[/bold cyan]")

            print_info("Starting agent graph execution...")
            exec_res = _execute_with_conflict_recovery(client, task_id)

            while True:
                if exec_res.status == "awaiting_approval":
                    console.print()
                    print_warning(
                        f"Task [bold cyan]{task_id}[/bold cyan] reached Human Approval Gate."
                    )
                    if exec_res.coder_summary:
                        console.print(
                            f"[bold cyan]Plan / Summary:[/bold cyan] {exec_res.coder_summary}"
                        )
                    render_diff(exec_res.pending_patch)

                    try:
                        approved = Confirm.ask(
                            "Approve these changes to be applied to the filesystem?", default=False
                        )
                    except (KeyboardInterrupt, typer.Abort):
                        console.print(
                            "\n[yellow]Interrupted by operator. No changes submitted.[/yellow]"
                        )
                        raise typer.Exit(code=0) from None

                    feedback: str | None = None
                    if not approved:
                        try:
                            feedback = (
                                Prompt.ask(
                                    "Rejection feedback (optional, press Enter to skip)", default=""
                                ).strip()
                                or None
                            )
                        except (KeyboardInterrupt, typer.Abort):
                            console.print(
                                "\n[yellow]Interrupted. Submitting rejection without feedback.[/yellow]"
                            )

                    print_info(f"Submitting decision ({'APPROVED' if approved else 'REJECTED'})...")
                    exec_res = _submit_approval_with_recovery(client, task_id, approved, feedback)
                    continue

                if exec_res.status == "completed":
                    print_success("Task executed and verified successfully.")
                    render_final_result(exec_res.final_result)
                    raise typer.Exit(code=0)

                if exec_res.status == "aborted":
                    print_warning(
                        f"Task execution was aborted: {exec_res.error or 'Operator rejected proposed changes.'}"
                    )
                    raise typer.Exit(code=0)

                if exec_res.status == "failed":
                    print_error(
                        f"Task execution failed: {exec_res.error or 'Execution failed in sandbox.'}"
                    )
                    if exec_res.test_result:
                        print_error(f"Test Exit Code: {exec_res.test_result.get('exit_code')}")
                    raise typer.Exit(code=1)

                if exec_res.status == "running":
                    print_info("Task execution is actively running on backend. Checking status...")
                    time.sleep(2)
                    task_check = client.get_task(task_id)
                    if task_check.status == "running":
                        continue
                    exec_res = client.run_task(task_id)
                    continue

                print_warning(f"Task concluded with state: {exec_res.status}")
                break

        except (KeyboardInterrupt, typer.Abort):
            console.print("\n[yellow]Operation aborted by user. Exiting cleanly.[/yellow]")
            raise typer.Exit(code=0) from None
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err


def _execute_with_conflict_recovery(client: IrtrixClient, task_id: str):
    try:
        return client.run_task(task_id)
    except ConflictError:
        print_warning("Backend reported 409 Conflict. Verifying current authoritative state...")
        task = client.get_task(task_id)
        if task.status in ("completed", "failed", "aborted"):
            return client.run_task(task_id)
        for _ in range(15):
            time.sleep(2)
            task = client.get_task(task_id)
            if task.status != "running":
                return client.run_task(task_id)
        raise


def _submit_approval_with_recovery(
    client: IrtrixClient,
    task_id: str,
    approved: bool,
    feedback: str | None,
):
    try:
        return client.submit_approval(task_id, approved=approved, feedback=feedback)
    except ApprovalStateError as err:
        print_error(f"Approval state mismatch: {err.message}")
        task = client.get_task(task_id)
        render_task(task, title="Authoritative Reconciled State")
        raise typer.Exit(code=4) from err
