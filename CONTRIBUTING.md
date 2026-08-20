# Contributing

Thanks for helping build GoldenGraphRAG! PRs, issues, and ontology examples are all
welcome.

## Dev environment

```bash
git clone https://github.com/BebopCode/GoldenGraphRAG.git && cd GoldenGraphRAG
uv sync --all-groups              # runtime + pytest/ruff + mkdocs (creates .venv)
source .venv/bin/activate         # then kg / pytest / ruff / mkdocs run bare
cp .env.example .env              # and edit
docker compose up -d              # AGE container — needed for integration tests
```

## Before you open a PR

```bash
pytest tests/unit                 # must pass (nothing external needed)
pytest tests/integration          # if you touched the store (auto-skips without the DB)
ruff check src tests scripts
ruff format src tests scripts
```

If your change touches docs, also run `mkdocs build --strict` — it must exit clean
(see the [development docs](https://bebopcode.github.io/GoldenGraphRAG/development/)
for the docs preview loop).

## Notes

- `pyproject.toml` declares the dependency floors; `uv.lock` is the committed
  exact lock. Add deps with `uv add` (or `uv add --group dev` / `--group docs`)
  and commit the regenerated lock — CI runs `uv sync --locked` and fails if the
  lock is stale.
- Keep new stages pluggable: anything swappable goes behind the existing ABCs
  (`LLMClient`, `GraphStore`, `Chunker`) — see the
  [architecture docs](https://bebopcode.github.io/GoldenGraphRAG/architecture/).
- For bug reports, include the log output and `kg info` (redact your API key).
