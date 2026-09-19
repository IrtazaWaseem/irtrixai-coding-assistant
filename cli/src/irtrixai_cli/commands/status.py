import typer

from irtrixai_cli.client import CLIError, IrtrixClient
from irtrixai_cli.output import print_error, render_combined_status


def status_command(ctx: typer.Context) -> None:
    """Displays combined health status for the backend service and LLM gateway."""
    api_url: str = ctx.obj["api_url"]
    with IrtrixClient(api_url) as client:
        try:
            combined = client.get_combined_status()
            render_combined_status(combined)
            if combined.backend is None:
                raise typer.Exit(code=3)
        except CLIError as err:
            print_error(err.message)
            raise typer.Exit(code=err.exit_code) from err
