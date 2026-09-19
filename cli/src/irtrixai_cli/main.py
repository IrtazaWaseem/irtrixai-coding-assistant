import typer

from irtrixai_cli.commands.run import run_composite_command
from irtrixai_cli.commands.status import status_command
from irtrixai_cli.commands.task import (
    approve_task_command,
    create_task_command,
    events_task_command,
    reject_task_command,
    run_task_command,
    status_task_command,
)
from irtrixai_cli.commands.workspace import (
    add_workspace_command,
    list_workspaces_command,
    tree_workspace_command,
)
from irtrixai_cli.config import resolve_api_url

app = typer.Typer(
    name="irtrixai",
    help="IrtrixAI Autonomous Coding Assistant CLI",
    no_args_is_help=True,
    add_completion=False,
)

workspace_app = typer.Typer(
    name="workspace",
    help="Inspect and manage workspace directory registrations",
    no_args_is_help=True,
)
task_app = typer.Typer(
    name="task", help="Create and manage supervised agent tasks", no_args_is_help=True
)

app.add_typer(workspace_app, name="workspace")
app.add_typer(task_app, name="task")


@app.callback()
def main(
    ctx: typer.Context,
    api_url: str | None = typer.Option(
        None,
        "--api-url",
        help="FastAPI backend host URL (overrides IRTRIXAI_API_URL)",
        envvar="IRTRIXAI_API_URL",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show diagnostic technical details"
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["api_url"] = resolve_api_url(api_url)
    ctx.obj["verbose"] = verbose


# Status Command
app.command(name="status", help="Display combined backend and model gateway health")(status_command)

# Workspace Commands
workspace_app.command(name="list", help="List all registered workspaces")(list_workspaces_command)
workspace_app.command(name="add", help="Register a new host workspace directory")(
    add_workspace_command
)
workspace_app.command(name="tree", help="Inspect directory structure for a workspace")(
    tree_workspace_command
)

# Task Commands
task_app.command(name="create", help="Create an agent coding task")(create_task_command)
task_app.command(name="status", help="Query authoritative task status")(status_task_command)
task_app.command(name="run", help="Trigger or resume task execution")(run_task_command)
task_app.command(name="approve", help="Approve proposed patch")(approve_task_command)
task_app.command(name="reject", help="Reject proposed patch with feedback")(reject_task_command)
task_app.command(name="events", help="View one-shot persisted event snapshot")(events_task_command)

# Primary Composite Workflow
app.command(
    name="run", help="Execute complete supervised lifecycle (create, run, inspect, approve, verify)"
)(run_composite_command)


if __name__ == "__main__":
    app()
