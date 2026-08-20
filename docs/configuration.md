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
| `LLM_TIMEOUT` | `120` | Per-request timeout, seconds — raise for slow reasoning models that think before answering |
| `LLM_MAX_RETRIES` | `2` | Retries per request on timeout / connection drops / 429 / 5xx, backing off 1/2/4/8s |
| `LLM_CONCURRENCY` | `2` | Parallel chunk extractions — [keep it low on hosted APIs](#concurrency) |
| `LLM_STRUCTURED_MODE` | `auto` | `auto \| json_schema \| json_object \| none` — see [structured outputs](providers.md) |
| `LLM_MAX_TOKENS` | *(unset)* | Cap output tokens; raise if you see `finish_reason=length` warnings (truncated JSON) |
| `LLM_ALLOWED_PROVIDERS` | *(unset)* | OpenRouter routing allowlist, comma-separated (e.g. `Groq,DeepInfra`) |
| `LLM_HTTP_REFERER` | *(unset)* | Sent as the `HTTP-Referer` header (OpenRouter attribution) |

### App

| Variable | Default | Description |
|---|---|---|
| `ONTOLOGY_PATH` | `config/ontologies/generic.yaml` | Which ontology to extract against |
| `CHUNKER` | `fixed` | `fixed \| structural` — see [Chunking strategies](#chunking-strategies) |
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
  concurrency: 2            # see "Concurrency" below before raising
  structured_mode: auto     # auto | json_schema | json_object | none
  # allowed_providers: [Groq, DeepInfra]   # OpenRouter routing allowlist
  # max_tokens: 4096
  # extra_headers:                          # e.g. OpenRouter attribution
  #   HTTP-Referer: https://example.com

ingest:
  chunker: fixed             # fixed | structural (CHUNKER env also works)
  fixed:
    chunk_size: 1200         # characters per chunk (fixed chunker only)
    chunk_overlap: 200       # overlap between adjacent chunks

extract:
  batch_size: 8             # chunks per progress flush (logging)
  max_retries: 1            # retries on malformed JSON before skipping a chunk

fusion:
  use_embeddings: false     # embedding-based dedup (not implemented yet)
```

## Concurrency

`LLM_CONCURRENCY` (default **2**) sets how many chunks are extracted in
parallel. The instinct is to raise it — don't, at least not on a hosted API.

**Hosted providers cap tokens per minute, not just requests.** The limit is
tiered by your org's lifetime spend (e.g. OpenAI Tier 1 gives `gpt-4o`
500 requests/min but only **30,000 tokens/min**), and the token cap binds
first: every extraction sends the ontology prompt plus the chunk
(~1–1.5k tokens) and receives verbose JSON back (~0.5–1.5k tokens), so a
30k budget is roughly **a dozen requests per minute** total.

High concurrency doesn't go faster past that point — it goes *slower and
lossier*:

1. Eight workers drain the token budget in seconds → the API answers
   everything with `429 Too Many Requests`.
2. The client backs off 1/2/4/8s, but a rate-limit window refills over up to
   ~60s — retries keep failing.
3. Retries exhaust → the chunk is **skipped** and logged, not requeued. The
   run finishes green with a silently incomplete graph.

A concurrency of 2 paces requests near the refill rate of most tiers: no
wasted 429 round-trips, no skipped chunks, and end-to-end time often barely
differs because workers aren't parked in retry loops.

**Raise it only when there is no token meter** — a self-hosted vLLM/Ollama
endpoint (vLLM's continuous batching makes 32 reasonable), or a paid tier
whose per-minute budget dwarfs your corpus.

**Spotting trouble:** `429` warnings in the log mean back off
(`LLM_CONCURRENCY=1`, or raise `LLM_MAX_RETRIES`); `LLM call failed
permanently` errors mean chunks were already skipped — re-run the ingest
after lowering concurrency.

## Chunking strategies

Two chunkers ship with the pipeline; pick one with the `CHUNKER` env var or
`ingest.chunker` in `settings.yaml`.

### `fixed` (default)

Character windows of `CHUNK_SIZE` (default 1200) with `CHUNK_OVERLAP` (default 200)
shared between adjacent windows. Windows are trimmed back to the last word boundary,
so an entity is never cut mid-token.

- **Predictable** — chunk count and size are the same for any document, so prompt
  sizes (and cost) are bounded up front.
- **Right for** unstructured text (prose dumps, transcripts, emails) and for keeping
  prompts safely inside a small model's context window.
- The overlap gives a statement that straddles a boundary a chance to extract from
  both sides.

### `structural`

Splits along the document's natural structure — markdown headers first, then a
heuristic section detector (ALL-CAPS titles like `PREAMBLE`, `Article N` / `Part III`,
numbered headings). The active heading *path* (e.g. `Part III > Article 21`) rides
along in each chunk's metadata, so the extractor still knows where a chunk came from.

- **Higher fidelity** — entities and their surrounding context stay on the same side
  of a chunk boundary, which measurably improves extraction.
- **Right for** documents with real structure: legal texts, specifications, markdown.
- **Caveats** — `CHUNK_SIZE` has no effect here (sections are kept whole), so chunk
  sizes vary, and one huge section becomes one huge chunk. If that bites, switch back
  to `fixed` or file an issue about exposing the structural chunker's `max_chars` cap
  in settings.

**Rule of thumb:** start with `fixed` (the default) for bounded, predictable
behavior; switch to `structural` when your documents have real headings and you
notice entities being split or losing their context.

## Multiple configurations

Every CLI command accepts `--env <file>` to point at a different `.env` — handy for
juggling ontologies, graphs, or LLM endpoints without editing your main `.env`:

```bash
kg ingest data/samples/constitution_sample.md --env .env.constitution
```

The repo ships [`.env.constitution`](https://github.com/BebopCode/GoldenGraphRAG/blob/main/.env.constitution)
as a worked example: it points at a local Ollama instance, the constitution ontology,
and a separate graph (`kg_graph_const`) so experiments don't pollute each other.
