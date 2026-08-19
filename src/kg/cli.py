"""Typer CLI entrypoint: ``kg init | ingest | query | info``.

Imports of heavy collaborators (store, pipeline) are done *inside* the command
bodies so ``kg --help`` stays fast and doesn't require the DB/LLM to be up.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import typer

app = typer.Typer(
    name="kg",
    help="Config-driven text-to-knowledge-graph pipeline (any OpenAI-compatible LLM + Apache AGE).",
    no_args_is_help=True,
)


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


@app.command()
def init(
    env: Path = typer.Option(None, help="Path to .env (default: project root)."),
) -> None:
    """Create the AGE graph (idempotent) and confirm connectivity."""
    from kg.config.loader import load_settings
    from kg.store.age_store import AgeGraphStore

    settings = load_settings(env_path=env)
    _setup_logging(settings.log_level)
    store = AgeGraphStore.from_settings(settings)
    store.init_graph(settings.db.graph_name)
    typer.secho(
        f"Graph '{settings.db.graph_name}' is ready on "
        f"{settings.db.host}:{settings.db.port}/{settings.db.dbname}.",
        fg=typer.colors.GREEN,
    )


@app.command()
def ingest(
    dataset: Path = typer.Argument(..., help="File or directory to ingest."),
    limit: int = typer.Option(None, "--limit", "-n", help="Stop after N chunks (partial run)."),
    env: Path = typer.Option(None, help="Path to .env (default: project root)."),
) -> None:
    """Run the full pipeline: load -> chunk -> extract -> fuse -> store."""
    from kg.config.loader import load_settings
    from kg.pipeline import run_pipeline

    settings = load_settings(env_path=env)
    _setup_logging(settings.log_level)
    stats = run_pipeline(dataset, settings=settings, limit=limit)
    typer.secho(
        f"Done. documents={stats['documents']} chunks={stats['chunks']} "
        f"nodes={stats['nodes']} edges={stats['edges']}",
        fg=typer.colors.GREEN,
    )


@app.command()
def query(
    cypher: str = typer.Argument(..., help='openCypher query, e.g. "MATCH (n) RETURN n LIMIT 10".'),
    env: Path = typer.Option(None, help="Path to .env (default: project root)."),
) -> None:
    """Run an openCypher query against the graph and print rows as JSON."""
    from kg.config.loader import load_settings
    from kg.store.age_store import AgeGraphStore

    settings = load_settings(env_path=env)
    _setup_logging(settings.log_level)
    store = AgeGraphStore.from_settings(settings)
    rows = store.query(cypher)
    typer.echo(json.dumps(rows, indent=2, default=str, ensure_ascii=False))


@app.command()
def info(
    env: Path = typer.Option(None, help="Path to .env (default: project root)."),
    check_llm: bool = typer.Option(
        False, "--check-llm", help="Ping the LLM endpoint (auth + model slug)."
    ),
) -> None:
    """Show the effective config and ontology (no DB needed)."""
    import json as _json

    from kg.config.loader import load_ontology, load_settings

    settings = load_settings(env_path=env)
    ontology = load_ontology(settings=settings)
    typer.echo(f"settings.llm = {_json.dumps(settings.llm.redacted(), default=str)}")
    typer.echo(f"settings.chunker = {settings.chunker}")
    typer.echo(
        f"ontology = {ontology.name} ({len(ontology.node_types)} node types, "
        f"{len(ontology.relationship_types)} relationship types)"
    )
    typer.echo("node labels:      " + ", ".join(sorted(ontology.node_labels())))
    typer.echo("relationship labels: " + ", ".join(sorted(ontology.relationship_labels())))

    if check_llm:
        from kg.llm.factory import build_llm_client

        llm = build_llm_client(settings.llm)
        typer.echo(_json.dumps(llm.health_check(), indent=2, default=str))
        llm.close()


if __name__ == "__main__":
    app()
