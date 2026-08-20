# Development

## One-time setup

```bash
git clone https://github.com/BebopCode/GoldenGraphRAG.git
cd GoldenGraphRAG
uv sync --all-groups              # runtime + pytest/ruff + mkdocs (creates .venv)
source .venv/bin/activate         # then kg / pytest / ruff / mkdocs run bare
cp .env.example .env              # and edit
docker compose up -d              # the AGE container (integration tests need it)
```

!!! note
    uv creates and manages `.venv` automatically on the first `uv sync`. Activate
    it (`source .venv/bin/activate`) and every tool runs bare, exactly as before
    the uv migration. If you have a leftover `env/` or a hand-made `.venv` from
    an earlier setup, you can simply delete it; uv will rebuild a clean one.

## Project structure

```
GoldenGraphRAG/
├── docker-compose.yml          # PostgreSQL 16 + Apache AGE
├── docker/init-age.sql         # creates extension + default graph on first start
├── config/
│   ├── settings.example.yaml   # tuning (chunk sizes, batch sizes, temperature)
│   └── ontologies/             # generic.yaml, constitution.yaml
├── data/samples/               # tiny committed samples
├── scripts/smoke_test.py       # end-to-end sanity run
├── src/kg/
│   ├── cli.py                  # `kg` Typer entrypoint
│   ├── config/                 # pydantic models + YAML/.env loader (validates at startup)
│   ├── llm/                    # LLMClient ABC + OpenAI-compatible client + provider factory
│   ├── ingest/                 # loaders + chunkers (structural / fixed)
│   ├── extract/                # ontology-constrained LLM extractor + prompts + schemas
│   ├── fusion/                 # entity resolution / dedup
│   ├── store/                  # GraphStore ABC + Apache AGE implementation
│   └── pipeline.py             # load → chunk → extract → fuse → store
└── tests/
    ├── unit/                   # config, chunkers, extractor (mocked LLM), fusion
    └── integration/            # AgeGraphStore round-trip (needs the container)
```

## Tests

```bash
pytest tests/unit               # needs nothing external (LLM + store mocked)
docker compose up -d            # then:
pytest tests/integration        # auto-skips if the DB isn't reachable
```

## Lint and format

```bash
ruff check src tests scripts
ruff format src tests scripts
```

## Smoke test

[`scripts/smoke_test.py`](https://github.com/BebopCode/GoldenGraphRAG/blob/main/scripts/smoke_test.py)
runs the full pipeline over `data/samples/example.txt` and prints ingest stats plus
sample graph contents. It needs the AGE container *and* a reachable LLM endpoint:

```bash
python scripts/smoke_test.py
```

## Working on these docs

The site is [MkDocs](https://www.mkdocs.org) + [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/),
built by [.github/workflows/docs.yml](https://github.com/BebopCode/GoldenGraphRAG/blob/main/.github/workflows/docs.yml)
and served at <https://bebopcode.github.io/GoldenGraphRAG/>.

```bash
mkdocs serve                    # live preview at http://127.0.0.1:8000/GoldenGraphRAG/
mkdocs build --strict           # what CI runs; must exit clean
```

!!! note
    The preview serves under the `/GoldenGraphRAG/` subpath (matching the
    published `site_url`); the bare `http://127.0.0.1:8000/` root will 404.

!!! warning "Linking to repo files"
    Links from a docs page to files *outside* `docs/` (e.g. `settings.example.yaml`)
    must be absolute GitHub URLs; relative paths break the strict build and 404 on
    the published site.

An auto-generated API reference ([mkdocstrings](https://mkdocstrings.github.io/))
is a planned follow-up; the docstrings throughout `src/kg` are already written with
that in mind.

## Dependency notes

- `pyproject.toml` declares the dependency floors; `uv.lock` is the committed,
  exact lock: `uv sync --locked` reproduces the environment bit-for-bit.
- Add a dependency with `uv add <pkg>` (or `uv add --group dev` / `--group docs`);
  the lock regenerates and gets committed with your change. CI fails if the lock
  is stale relative to `pyproject.toml`.
