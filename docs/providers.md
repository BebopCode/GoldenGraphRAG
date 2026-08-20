# LLM Providers

Every provider from OpenRouter to vLLM to a local Ollama speaks the OpenAI Chat
Completions API, so one client covers all of them. **The provider name only selects
preset defaults** (base URL, default model, whether a key is required): what actually
routes the call is `LLM_BASE_URL` + `LLM_MODEL` + `LLM_API_KEY` in `.env`.

| Provider | `LLM_PROVIDER` | Endpoint | Notes |
|---|---|---|---|
| [OpenRouter](https://openrouter.ai) | `openrouter` | hosted | one key, hundreds of models |
| [vLLM](https://docs.vllm.ai) | `vllm` | self-hosted | the usual choice for sensitive corpora |
| OpenAI | `openai` | hosted | |
| Together / Fireworks | `together` / `fireworks` | hosted | |
| LiteLLM proxy | `litellm` | self-hosted gateway | |
| Ollama | `ollama` | local | same client, `http://localhost:11434/v1` |

=== "OpenRouter"

    1. Create a key at [openrouter.ai/keys](https://openrouter.ai/keys) and add credit.
    2. Set `.env`:
       ```bash
       LLM_PROVIDER=openrouter
       LLM_API_KEY=sk-or-...
       LLM_MODEL=qwen/qwen3-30b-a3b-instruct    # slugs are vendor/model; check the model page
       ```
    3. Sanity-check the key and slug before ingesting:
       ```bash
       curl https://openrouter.ai/api/v1/chat/completions \
         -H "Authorization: Bearer $LLM_API_KEY" -H "Content-Type: application/json" \
         -d '{"model":"qwen/qwen3-30b-a3b-instruct","messages":[{"role":"user","content":"say ok"}]}'
       ```

    !!! warning "Things worth knowing"
        - **Structured-output support is per endpoint, not per model.** The client sets
          `provider.require_parameters = true` whenever a schema is sent, so OpenRouter
          only routes to endpoints that honour `response_format`; without it you can
          get valid JSON that silently ignores your ontology. On models whose *only*
          endpoint lacks that support (most `:free` tiers, e.g.
          `nvidia/nemotron-3.5-lightning:free`), the constraint matches nothing and
          OpenRouter answers `404 No endpoints found`; the client treats that as a
          rejection and falls back to `json_object` (the schema stays in the prompt).
          Pin `LLM_STRUCTURED_MODE=json_object` to skip that one probe request per run.
        - **Rate limits (429s) are normal.** The client retries with backoff; keep
          `LLM_CONCURRENCY` low (the default 2 is a sane start; upstream providers
          meter tokens per minute, not just requests) until you know your limits.
        - **Prompts transit third-party inference providers.** For sensitive corpora pin
          `LLM_ALLOWED_PROVIDERS` to vendors your legal team approved, or use vLLM.
        - Model slugs can be re-pointed upstream; pin dated slugs where offered to keep
          extraction output stable.

=== "vLLM"

    ```bash
    uv tool install vllm    # standalone server, own environment, doesn't touch .venv
    vllm serve Qwen/Qwen3-30B-A3B-Instruct \
      --served-model-name kg-extractor \
      --api-key "$VLLM_API_KEY" \
      --host 0.0.0.0 --port 8000 \
      --max-model-len 8192 \
      --gpu-memory-utilization 0.90 \
      --tensor-parallel-size 2          # = number of GPUs
    ```

    ```bash
    # .env
    LLM_PROVIDER=vllm
    LLM_BASE_URL=http://localhost:8000/v1     # must end in /v1
    LLM_MODEL=kg-extractor                    # = --served-model-name
    LLM_API_KEY=$VLLM_API_KEY                 # whatever you passed to --api-key
    ```

    !!! tip "Things worth knowing"
        - **`--max-model-len` must exceed prompt + ontology + output.** Truncated
          extractions log a `finish_reason=length` warning; raise `--max-model-len`
          and `LLM_MAX_TOKENS`, or shrink `CHUNK_SIZE`.
        - **Constrained decoding is genuinely enforced** here, unlike prompt-only JSON:
          a real accuracy win for ontology-constrained extraction. The structured-output
          parameter names changed across vLLM versions (`guided_json` was removed in
          0.12.0); the client starts with standard `response_format` and falls back
          automatically, so both old and new servers work. Pin `LLM_STRUCTURED_MODE`
          once you know which you're on.
        - Concurrency is nearly free under vLLM's continuous batching; raise
          `LLM_CONCURRENCY` (32 is reasonable) rather than adding worker processes.

=== "Ollama"

    Pull a model and point the pipeline at Ollama's OpenAI-compatible port:

    ```bash
    ollama pull llama3.1
    ```

    ```bash
    # .env
    LLM_PROVIDER=ollama
    LLM_MODEL=llama3.1
    LLM_BASE_URL=http://localhost:11434/v1     # note the /v1
    ```

    No API key needed. Expect slower extraction than hosted providers; lower
    `LLM_CONCURRENCY` accordingly.

## Structured-output negotiation

Endpoints differ in how (or whether) they enforce a JSON schema. The client handles
this automatically in `auto` mode: it starts strict (`response_format=json_schema`),
degrades through vLLM's legacy spellings when a 400 suggests rejection, and lands on
plain `json_object` as the floor, remembering the mode that worked, so the probe
costs one request per process, not per chunk. Pin `LLM_STRUCTURED_MODE` in `.env`
if you already know what your endpoint supports.
