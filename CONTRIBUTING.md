# Contributing

Thanks for helping build GoldenGraphRAG! PRs, issues, and ontology examples are all
welcome.

## Dev environment

```bash
git clone https://github.com/BebopCode/GoldenGraphRAG.git && cd GoldenGraphRAG
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,docs]"
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

- `pyproject.toml` is the source of truth for dependencies;
  `requirements*.txt` are pinned snapshots and can lag.
- Keep new stages pluggable: anything swappable goes behind the existing ABCs
  (`LLMClient`, `GraphStore`, `Chunker`) — see the
  [architecture docs](https://bebopcode.github.io/GoldenGraphRAG/architecture/).
- For bug reports, include the log output and `kg info` (redact your API key).
