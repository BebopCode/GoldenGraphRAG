# GoldenGraphRAG

**Turn any text dataset into a queryable knowledge graph using any OpenAI-compatible
LLM and PostgreSQL + Apache AGE.**

GoldenGraphRAG (the Python package is `kg-pipeline`, the CLI is `kg`) is a modular,
config-driven pipeline: it loads documents, chunks them along their natural structure,
extracts entities and relationships with an LLM constrained to a declared ontology,
fuses duplicate entities into canonical nodes, and stores the result as a property
graph in Apache AGE — which runs openCypher *inside* PostgreSQL.

## Why it's shaped this way

- **Any OpenAI-compatible LLM.** OpenRouter, vLLM, OpenAI, Together, Fireworks,
  LiteLLM, Ollama — every provider speaks the Chat Completions API, so the LLM is a
  set of `.env` values, not a code path.
- **New domain = one YAML file.** The ontology declares the only legal node and
  relationship labels. Swapping domains (Constitution → movies → anything) is an edit
  to that file, never to Python.
- **Pluggable chunking.** Fixed-size windows by default, or structure-aware splitting
  along headings and sections — entities keep their context instead of being cut
  mid-sentence.
- **Ontology-constrained extraction.** Off-ontology output is dropped and logged;
  endpoints with structured outputs enforce the schema at decode time.
- **Entity fusion.** The same real-world entity shows up as "Article 21", "Art. 21",
  "ARTICLE 21" across chunks — fusion normalizes and merges them before storage.
- **Idempotent writes.** Store upserts use `MERGE`, so re-running ingestion updates
  the graph instead of duplicating it.

## Get started

```bash
git clone https://github.com/BebopCode/GoldenGraphRAG.git
```

Head to the [Quickstart](quickstart.md) for the full setup, or jump straight to:

- [Configuration](configuration.md) — every `.env` variable and `settings.yaml` knob
- [LLM Providers](providers.md) — OpenRouter, vLLM, Ollama, and friends
- [Ontologies](ontologies.md) — define a new domain in YAML
- [Architecture](architecture.md) — how the five stages fit together

!!! note "Naming, demystified"
    The repository is **GoldenGraphRAG**, the installable Python package is
    **kg-pipeline**, and the command you run is **`kg`** (e.g. `kg ingest ...`).
    They're all the same project.
