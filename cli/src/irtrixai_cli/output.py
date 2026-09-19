from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

from irtrixai_cli.models import (
    CLIEvent,
    CombinedStatus,
    ExecutionResponse,
    FileNode,
    TaskResponse,
    Workspace,
    WorkspaceTree,
)

console = Console()
error_console = Console(stderr=True)


def format_bytes(bytes_count: int | None) -> str:
    if bytes_count is None:
        return ""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    if bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    return f"{bytes_count / (1024 * 1024):.1f} MB"


def print_success(msg: str) -> None:
    console.print(f"[bold green]✓[/bold green] {msg}")


def print_info(msg: str) -> None:
    console.print(f"[bold cyan]●[/bold cyan] {msg}")


def print_warning(msg: str) -> None:
    console.print(f"[bold yellow]⚠[/bold yellow] {msg}")


def print_error(msg: str) -> None:
    error_console.print(f"[bold red]✕[/bold red] {msg}")


def render_diff(patch_text: str | None) -> None:
    if not patch_text or not patch_text.strip():
        console.print("[dim]No unified diff proposed.[/dim]")
        return
    syntax = Syntax(patch_text, "diff", theme="ansi_dark", word_wrap=True)
    console.print(
        Panel(
            syntax,
            title="[bold]Proposed Modifications (Unified Diff)[/bold]",
            border_style="yellow",
        )
    )


def render_combined_status(combined: CombinedStatus) -> None:
    b_table = Table(title="Backend Service", show_header=True, header_style="bold cyan")
    b_table.add_column("Property", style="bold")
    b_table.add_column("Value")

    if combined.backend:
        b_table.add_row("Status", f"[green]{combined.backend.status}[/green]")
        b_table.add_row("Version", combined.backend.version)
        b_table.add_row("Environment", combined.backend.environment)
    else:
        b_table.add_row("Status", f"[bold red]Offline ({combined.backend_error})[/bold red]")

    console.print(b_table)
    console.print()

    l_table = Table(title="Model Gateway", show_header=True, header_style="bold cyan")
    l_table.add_column("Property", style="bold")
    l_table.add_column("Value")

    if combined.llm:
        l_table.add_row("Provider", combined.llm.provider)
        l_table.add_row("Model", combined.llm.model)
        l_table.add_row("Display Name", combined.llm.display_name)
        if combined.llm.fallback_provider:
            l_table.add_row("Fallback Provider", combined.llm.fallback_provider)

        caps = [
            f"[green]✓ {k}[/green]" if v else f"[dim]✕ {k}[/dim]"
            for k, v in combined.llm.capabilities.items()
        ]
        l_table.add_row("Capabilities", ", ".join(caps) if caps else "None reported")
    else:
        l_table.add_row("Gateway Info", f"[yellow]Unavailable ({combined.llm_error})[/yellow]")

    console.print(l_table)


def render_workspaces(workspaces: list[Workspace]) -> None:
    if not workspaces:
        print_info("No registered workspaces found.")
        return

    table = Table(
        title=f"Registered Workspaces ({len(workspaces)})",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("ID", style="dim")
    table.add_column("Name", style="bold")
    table.add_column("Root Path", style="cyan")

    for w in workspaces:
        table.add_row(w.id, w.name, w.root_path)

    console.print(table)


def _populate_tree(node: FileNode, tree_branch: Tree) -> None:
    if not node.children:
        return
    for child in node.children:
        size_tag = f" [dim]({format_bytes(child.size)})[/dim]" if child.size is not None else ""
        if child.type == "directory":
            branch = tree_branch.add(f"[bold blue]📁 {child.name}/[/bold blue]")
            _populate_tree(child, branch)
        else:
            tree_branch.add(f"[green]📄 {child.name}[/green]{size_tag}")


def render_workspace_tree(tree_data: WorkspaceTree) -> None:
    root_tree = Tree(
        f"[bold cyan]📁 {tree_data.root_path}[/bold cyan] [dim]({tree_data.total_entries} entries)[/dim]"
    )
    for node in tree_data.tree:
        size_tag = f" [dim]({format_bytes(node.size)})[/dim]" if node.size is not None else ""
        if node.type == "directory":
            branch = root_tree.add(f"[bold blue]📁 {node.name}/[/bold blue]")
            _populate_tree(node, branch)
        else:
            root_tree.add(f"[green]📄 {node.name}[/green]{size_tag}")

    console.print(root_tree)
    if tree_data.truncated:
        console.print("[yellow]⚠ Directory tree was truncated due to depth/entry limits.[/yellow]")


def render_task(task: TaskResponse, title: str = "Task") -> None:
    color = (
        "green"
        if task.status == "completed"
        else "yellow"
        if task.status == "awaiting_approval"
        else "cyan"
    )
    table = Table(title=title, show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Task ID", f"[cyan]{task.id}[/cyan]")
    table.add_row("Workspace ID", f"[cyan]{task.workspace_id}[/cyan]")
    table.add_row("Status", f"[{color}]{task.status.upper()}[/{color}]")
    if task.error:
        table.add_row("Error", f"[red]{task.error}[/red]")
    console.print(table)


def render_execution(res: ExecutionResponse) -> None:
    status_color = (
        "green"
        if res.status == "completed"
        else "yellow"
        if res.status == "awaiting_approval"
        else "red"
        if res.status in ("failed", "aborted")
        else "cyan"
    )
    print_info(
        f"Task [bold cyan]{res.task_id}[/bold cyan] state: [{status_color}]{res.status.upper()}[/{status_color}]"
    )

    if res.coder_summary:
        console.print(Panel(res.coder_summary, title="Coder Summary", border_style="cyan"))

    if res.pending_patch:
        render_diff(res.pending_patch)

    if res.error:
        print_error(f"Execution Error: {res.error}")


def render_events(events: list[CLIEvent]) -> None:
    if not events:
        print_info("No events recorded for this task.")
        return

    table = Table(
        title=f"Task Event Snapshot ({len(events)} events)",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Time", style="dim")
    table.add_column("Type", style="bold")
    table.add_column("Title", style="cyan")
    table.add_column("Description")

    for e in events:
        time_str = e.timestamp.split("T")[-1][:8] if "T" in e.timestamp else e.timestamp
        table.add_row(time_str, e.type, e.title, e.description)

    console.print(table)


def render_final_result(final: dict[str, Any] | None) -> None:
    if not final:
        return
    summary = final.get("summary", "No summary provided.")
    files = final.get("files_changed", [])
    tests = final.get("tests", [])

    panel_text = f"[bold]Summary:[/bold] {summary}\n"
    if files:
        panel_text += f"\n[bold]Files Mutated:[/bold] {', '.join(files)}"
    if tests:
        panel_text += f"\n[bold]Tests Executed:[/bold] {', '.join(tests)}"

    console.print(
        Panel(
            panel_text, title="[bold green]Execution Finalized[/bold green]", border_style="green"
        )
    )
