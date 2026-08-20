# Quickstart

From zero to a queryable knowledge graph in about five minutes.

## Prerequisites

- **Python 3.11+**
- **Docker** (+ Docker Compose)
- **An LLM endpoint.** Anything that speaks the OpenAI Chat Completions API.
  The fastest path is an [OpenRouter](https://openrouter.ai) key with a little credit;
  fully-local works too via Ollama or vLLM. See the
  [provider matrix](providers.md) for all of them.

## 1. Clone and configure

```bash
git clone https://github.com/BebopCode/GoldenGraphRAG.git
cd GoldenGraphRAG
cp .env.example .env
```

Edit `.env` — at minimum set `POSTGRES_PASSWORD` and your `LLM_API_KEY`:

```bash
POSTGRES_PASSWORD=choose-one
LLM_PROVIDER=openrouter
LLM_API_KEY=sk-or-...
```

Every variable is documented in [Configuration](configuration.md).

## 2. Start the database

```bash
docker compose up -d        # PostgreSQL 16 + Apache AGE
```

The container auto-creates the AGE extension and a default graph on first start.
Check it's healthy:

```bash
docker compose ps           # kg-age should show (healthy)
```

## 3. Install

```bash
uv sync && source .venv/bin/activate   # creates .venv + the `kg` console command
```

!!! tip "Reproducible installs"
    `uv.lock` pins exact versions for every dependency, so `uv sync` gives you
    the same environment the authors tested with — no extra step needed.

After activating once, every command on this page runs as plain `kg ...` — same
as before the uv migration. (`uv run kg ...` also works if you'd rather not
activate.)

## 4. Sanity-check the setup

```bash
kg info                     # effective config + ontology (no DB/LLM needed)
kg info --check-llm         # pings the endpoint: wrong URL / dead key fails in seconds
```

`kg info --check-llm` is the cheapest way to catch a bad base URL, model slug, or
key *before* a long ingest.

## 5. Build your first graph

```bash
kg init                                   # create the AGE graph (idempotent)
kg ingest data/samples/example.txt        # run the full pipeline
kg query "MATCH (n) RETURN n LIMIT 10"    # run an openCypher query
```

That's the whole pipeline: load → chunk → extract → fuse → store. Point
`kg ingest` at any `.txt` / `.md` / `.json` / `.csv` file or directory.

## Where next?

- Ingest a bigger, structured sample: `kg ingest data/samples/constitution_sample.md`
  with the [constitution ontology](ontologies.md#shipped-examples)
- [Define your own ontology](ontologies.md) for your domain
- [Example queries](cli.md#example-queries) to explore the graph
- Something went wrong? → [Troubleshooting](troubleshooting.md)
