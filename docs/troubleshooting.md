# Troubleshooting

## Setup

**`docker compose ps` shows the container unhealthy**

The AGE container runs `docker/init-age.sql` only on *first* boot (when the `age_data`
volume is empty). If the container won't come healthy:

```bash
docker compose down             # add -v to wipe the volume and re-init from scratch
docker compose up -d
```

Note that `-v` deletes your graphs.

**Wrong virtualenv**

uv creates and manages `.venv`; if you have a leftover `env/` or a hand-made
`.venv` from an earlier setup, `rm -rf env .venv && uv sync` rebuilds a clean one.
`which python` (or `which kg`) tells you which environment you're currently in;
activate with `source .venv/bin/activate` after syncing.

**`kg` command not found**

It comes from `uv sync` (a console script defined in pyproject). If it's missing,
you either skipped that step or you're in a different venv than the one uv created.
Activate with `source .venv/bin/activate`; there is no `python -m kg` fallback.

## LLM problems

**Fastest diagnosis: `kg info --check-llm`**: it pings the endpoint with a tiny
request and reports wrong base URL / dead key / bad model slug in seconds.

| Symptom | Likely cause / fix |
|---|---|
| 401/403 | Key wrong or out of credit (`openrouter.ai/keys` for OpenRouter) |
| 404 | `LLM_BASE_URL` is missing the `/v1` path; the loader rejects this at startup for exactly that reason |
| 404 on the model | `LLM_MODEL` slug is wrong for this provider; check the model page |
| 404 `No endpoints found that can handle the requested parameters` | OpenRouter had no endpoint for the model that supports structured outputs (typical for `:free` tiers). The client auto-falls back to `json_object`; the log warning is informational. Pin `LLM_STRUCTURED_MODE=json_object` to skip the probe |
| 429s in the log | You're hitting your tier's **tokens-per-minute** cap (spend-tier based), not requests. The client retries with backoff; lower `LLM_CONCURRENCY` (2 is the default; 1 if it persists) or raise `LLM_MAX_RETRIES`. `LLM call failed permanently` = chunks were skipped; re-run after lowering |
| `finish_reason=length` warnings | Output truncated → lossy extraction. Raise `LLM_MAX_TOKENS` / vLLM `--max-model-len`, or shrink `CHUNK_SIZE` |
| Valid JSON that ignores the ontology | Endpoint silently ignores `response_format`. The OpenRouter client sets `require_parameters` to prevent this; elsewhere, pin `LLM_STRUCTURED_MODE` or switch endpoints |

## Extraction problems

**Fewer entities than expected**

Check the `INFO` log for `dropping off-ontology` lines; the model emitted labels your
ontology doesn't declare. Either tighten the prompt (lower temperature), improve the
model, or extend the ontology if the label is genuinely part of your domain.

**A chunk "yielded no parseable JSON; skipped"**

The model returned prose or truncated JSON twice. Usually the model is too small for
structured output; try a larger one, or reduce `CHUNK_SIZE` so responses fit
`LLM_MAX_TOKENS`.

**Duplicate-looking nodes in the graph**

Fusion is normalized-string matching ("Article 21" ≡ "Art. 21"), not semantic:
"the right to life" and "Article 21" stay separate. Embedding-based fusion is a
planned follow-up (`fusion.use_embeddings` is the reserved switch).

## Known limitations

This project deliberately builds the **graph-construction** pipeline only. It is
honest about what it does not do yet:

- **No retrieval / QA layer.** It builds the graph; querying it intelligently
  (GraphRAG-style retrieval + answering) is a future phase.
- **No text-to-Cypher.** Queries are hand-written openCypher.
- **No web UI**: CLI only.
- **Fusion is string-based** (see above); semantic aliases need embeddings, which
  would need their own endpoint; vLLM can serve one.
- **Extraction quality** depends on the model and prompt; the ontology constraint
  does most of the heavy lifting, and endpoints with structured outputs enforce it
  at decode time.
- **Store writes are single-threaded** (one `MERGE` per node/edge). Extraction is
  concurrent; batch `UNWIND` upserts are the natural next step for large datasets.
- **Ingest is not resumable.** A failed run restarts extraction from scratch;
  per-chunk content hashing to skip already-extracted chunks is a natural follow-up.

Still stuck? Open an issue at
[github.com/BebopCode/GoldenGraphRAG/issues](https://github.com/BebopCode/GoldenGraphRAG/issues)
with the log output and your `kg info` (redact your API key).
