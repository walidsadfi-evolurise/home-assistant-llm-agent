from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from haagent.agent import summarize_verdicts
from haagent.config import Settings
from haagent.factory import make_agent

app = typer.Typer(help="Talk to your Home Assistant, with guardrails.", no_args_is_help=True)
console = Console()


@app.command()
def ask(
    text: str,
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm risky actions without asking"),
    dry_run: bool = typer.Option(False, help="Plan and judge, do not call Home Assistant"),
) -> None:
    """Say what you want; the agent plans, checks the policy, asks before risky actions, then acts."""
    s = Settings()
    if dry_run:
        s.dry_run = True
    agent = make_agent(s)
    out = agent.handle(text, confirm=yes)
    if out.verdicts:
        console.print(summarize_verdicts(out.verdicts))
    if out.status == "pending_confirmation" and out.confirmation_id:
        if typer.confirm("Confirmer ces actions ?", default=False):
            out = agent.confirm(out.confirmation_id)
        else:
            console.print("[yellow]Annulé.[/]")
            return
    colour = {
        "done": "green",
        "refused": "red",
        "clarify": "yellow",
        "dry_run": "cyan",
        "nothing": "dim",
        "pending_confirmation": "yellow",
    }[out.status]
    console.print(f"[{colour}]{out.status}[/] · {out.reply}")
    for e in out.executions:
        mark = "[green]✓[/]" if e.ok and e.verified is not False else "[red]✗[/]"
        console.print(
            f"  {mark} {e.action.describe()}  {e.before or '?'} → {e.after or '?'}"
            + (f"  [red]{e.error}[/]" if e.error else "")
        )


@app.command()
def entities(domain: str = typer.Option("", help="Filter by domain, e.g. light")) -> None:
    """List the entities the agent is allowed to see and control."""
    agent = make_agent(Settings())
    table = Table(title="Entities visible to the agent")
    for col in ("entity_id", "name", "state", "controllable"):
        table.add_column(col)
    for e in agent.policy.visible(agent.ha.states()):
        if domain and e.domain != domain:
            continue
        table.add_row(
            e.entity_id, e.name, e.state, "yes" if agent.policy.entity_allowed(e.entity_id) else "read-only"
        )
    console.print(table)


@app.command()
def check() -> None:
    """Connectivity and policy sanity check."""
    agent = make_agent(Settings())
    console.print(f"Home Assistant: [green]{agent.ha.ping()}[/]")
    ents = agent.ha.states()
    vis = agent.policy.visible(ents)
    ctrl = [e for e in vis if agent.policy.entity_allowed(e.entity_id)]
    console.print(
        f"{len(ents)} entities, {len(vis)} visible, {len(ctrl)} controllable, planner={agent.planner.name}"
    )


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8090) -> None:
    """Start the HTTP API."""
    import uvicorn

    uvicorn.run("haagent.api:app", host=host, port=port)


if __name__ == "__main__":
    app()
