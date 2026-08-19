# Configuration

All configuration is loaded and validated through pydantic **at startup** — a missing
or invalid value fails immediately, never mid-run. There are three inputs:

| Source | What lives there | Template |
|---|---|---|
| `.env` | Secrets and hosts: DB credentials, LLM endpoint + key | [`.env.example`](https://github.com/BebopCode/GoldenGraphRAG/blob/main/.env.example) |
| `config/settings.yaml` | Tuning knobs: chunk sizes, temperature, concurrency | [`config/settings.example.yaml`](https://github.com/BebopCode/GoldenGraphRAG/blob/main/config/settings.example.yaml) |
| `config/ontologies/*.yaml` | The domain definition: node/relationship types | see [Ontologies](ontologies.md) |

**Env values win** where `.env` and `settings.yaml` overlap.

## `.env` reference

### PostgreSQL / Apache AGE

| Variable | Default | Description |
|---|---|---|
| `POSTGRES_USER` | *(required)* | Database user |
| `POSTGRES_PASSWORD` | *(required)* | Database password |
| `POSTGRES_DB` | *(required)* | Database name |
| `POSTGRES_HOST` | `localhost` | Where the AGE container is reachable |
| `POSTGRES_PORT` | `5432` | Database port |
| `AGE_GRAPH_NAME` | `kg_graph` | Graph name inside AGE |

### LLM

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openrouter` | Picks preset defaults; see the [provider matrix](providers.md) |
| `LLM_API_KEY` | *(required for hosted)* | API key |
| `LLM_BASE_URL` | *(preset)* | Must include the `/v1` path |
| `LLM_MODEL` | *(preset)* | Model slug / served-model-name |
| `LLM_TIMEOUT` | `120` | Per-request timeout, seconds |
| `LLM_MAX_RETRIES` | `2` | Retries with backoff |
| `LLM_CONCURRENCY` | `8` | Parallel chunk extractions |
| `LLM_STRUCTURED_MODE` | `auto` | `auto \| json_schema \| json_object \| none` |
| `LLM_MAX_TOKENS` | *(unset)* | Cap output tokens |
| `LLM_ALLOWED_PROVIDERS` | *(unset)* | OpenRouter routing allowlist, comma-separated |

### App

| Variable | Default | Description |
|---|---|---|
| `ONTOLOGY_PATH` | `config/ontologies/generic.yaml` | Which ontology to extract against |
| `CHUNKER` | `structural` | `structural \| fixed` |
| `LOG_LEVEL` | `INFO` | Python logging level |

## `settings.yaml` reference

Copy `config/settings.example.yaml` to `config/settings.yaml` and edit — the example's
defaults apply if the file is absent. Everything here is non-secret tuning:

```yaml
llm:
  temperature: 0.0          # deterministic extraction
  json_mode: true
  timeout: 120
  max_retries: 2
  concurrency: 8
  structured_mode: auto     # auto | json_schema | json_object | none
  # allowed_providers: [Groq, DeepInfra]   # OpenRouter routing allowlist
  # max_tokens: 4096
  # extra_headers:                          # e.g. OpenRouter attribution
  #   HTTP-Referer: https://example.com

ingest:
  chunker: structural       # structural | fixed (CHUNKER env also works)
  fixed:
    chunk_size: 1200        # characters per chunk (fixed chunker only)
    chunk_overlap: 200      # overlap between adjacent chunks

extract:
  batch_size: 8             # chunks per progress flush (logging)
  max_retries: 1            # retries on malformed JSON before skipping a chunk

fusion:
  use_embeddings: false     # embedding-based dedup (not implemented yet)
```

## Multiple configurations

Every CLI command accepts `--env <file>` to point at a different `.env` — handy for
juggling ontologies, graphs, or LLM endpoints without editing your main `.env`:

```bash
kg ingest data/samples/constitution_sample.md --env .env.constitution
```

The repo ships [`.env.constitution`](https://github.com/BebopCode/GoldenGraphRAG/blob/main/.env.constitution)
as a worked example: it points at a local Ollama instance, the constitution ontology,
and a separate graph (`kg_graph_const`) so experiments don't pollute each other.
