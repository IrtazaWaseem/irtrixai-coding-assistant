import typer

from irtrixai_cli.client import CLIError, IrtrixClient
from irtrixai_cli.output import (
    print_error,
    print_success,
    render_workspace_tree,
    render_workspaces,
)


def list_workspaces_command(ctx: typer.Context) -> None:
    """Lists all registered workspace directories."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            workspaces = client.list_workspaces()
            render_workspaces(workspaces)
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err


def add_workspace_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", "-n", help="Human-readable identifier"),
    root_path: str = typer.Option(
        ..., "--root-path", "-p", help="Absolute host path to workspace root"
    ),
) -> None:
    """Registers a new host workspace directory without inspecting local files."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            ws = client.create_workspace(name=name, root_path=root_path)
            print_success(f"Registered workspace [bold]{ws.name}[/bold] (ID: [cyan]{ws.id}[/cyan])")
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err


def tree_workspace_command(
    ctx: typer.Context,
    workspace_id: str = typer.Argument(..., help="ID of the registered workspace"),
    max_depth: int = typer.Option(3, "--max-depth", "-d", help="Tree traversal depth (1 to 10)"),
) -> None:
    """Displays the filesystem directory structure for a registered workspace."""
    if not (1 <= max_depth <= 10):
        print_error("--max-depth must be an integer between 1 and 10.")
        raise typer.Exit(code=2)

    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            tree_data = client.get_workspace_tree(workspace_id=workspace_id, max_depth=max_depth)
            render_workspace_tree(tree_data)
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err
