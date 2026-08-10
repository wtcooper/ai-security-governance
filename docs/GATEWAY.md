# The model gateway

Every compute engine in this project — Inspect AI, `mcp-scanner`, `skill-scanner` — reaches
models through **one OpenAI-compatible endpoint**. The application never holds a
provider-native model string or a provider key. It sees only **aliases**.

That is the whole design: swapping what sits behind an alias is a gateway change the governance
layer never notices.

```
GATEWAY_BASE_URL=http://gateway:4000/v1
GATEWAY_API_KEY=sk-local
```

Point those at the bundled LiteLLM container, a corporate LiteLLM instance, a local vLLM
server, or `api.openai.com`, and nothing else changes. A direct provider key is *supported*,
never *assumed*.

## The bundled config is an example

`gateway/litellm_config.yaml` exists so a clean checkout runs: a couple of small local models
to develop against for free, plus mock routes so the stack boots and passes preflight with no
API key at all.

**A real deployment replaces it.** Model choice ages badly, and yours depends on what your
organisation serves, what your judge budget is, and which models you are being asked to
onboard. Expect a production config to be considerably more involved — real routing,
credentials, rate limits, fallbacks, cost controls.

## The two roles that need filling

| Role | What it needs |
|---|---|
| **Subject** | The model under evaluation. Whatever you are deciding about. |
| **Judge** | Grades open-ended answers for the three judged benchmarks. It has to follow a grading rubric on security content *and not refuse it* — a judge that will not grade silently corrupts scores, which is why its reliability is measured and can void a run. |

A third alias, the **scanner analyzer**, is used by `mcp-scanner` and `skill-scanner` for their
LLM-as-judge analyzers. It reasons about code rather than grading benchmark answers, so it is
configured separately (`SCANNER_MODEL`).

## Onboarding a local model (Ollama)

1. Pull it on the host:

   ```bash
   ollama pull <model>
   ```

2. Add an alias to `gateway/litellm_config.yaml`:

   ```yaml
   model_list:
     - model_name: my-local-model        # the alias the app will see
       litellm_params:
         model: ollama/<model>           # the real upstream name
         api_base: os.environ/OLLAMA_API_BASE
   ```

3. Restart the gateway and confirm the app can see it:

   ```bash
   docker compose up -d --build gateway
   curl -s localhost:8000/api/models       # the alias should be listed
   ```

4. Prove the route actually works before spending a run on it:

   ```bash
   curl -s -X POST localhost:8000/api/preflight \
     -H 'Content-Type: application/json' \
     -d '{"model":"my-local-model","judge_model":"my-local-model"}'
   ```

   Preflight performs a **real completion** and returns the upstream error body verbatim on
   failure. This is the fastest way to diagnose a bad route.

Ollama runs on the host by default and Colima maps `host.docker.internal` to it. If that
mapping misbehaves, `docker compose --profile local-models up` runs Ollama in-cluster instead.

## Onboarding an API-based model

1. Put the provider key in `./.env` at the repository root. It is read by the **gateway
   container only** — never by the application.

   ```
   MY_PROVIDER_API_KEY=sk-...
   ```

2. Add the alias, referencing the key by environment variable rather than inlining it:

   ```yaml
   model_list:
     - model_name: my-hosted-judge
       litellm_params:
         model: <provider>/<model-name>
         api_key: os.environ/MY_PROVIDER_API_KEY
   ```

3. Pass the key through to the gateway service in `compose.yaml` if it is not already listed:

   ```yaml
   services:
     gateway:
       environment:
         MY_PROVIDER_API_KEY: ${MY_PROVIDER_API_KEY:-}
   ```

4. Rebuild, then preflight it as above.

5. If you want it to be the default judge, set `DEFAULT_JUDGE_MODEL` to the **alias**, or change
   `judge.default_model` in the AI-model policy — the latter is versioned, which is usually what
   you want for a governance setting.

## The alias rule

**No slashes or colons in an alias.** Inspect parses model strings as
`openai-api/<provider>/<model>` and splits on `/`, so an upstream name of the common
`family:variant` form needs an alias like `family-variant`. The alias is what the app sees; the
real name stays in `litellm_params.model`.

## Why the gateway is a separate container

`litellm[proxy]` requires `boto3>=1.43.1`, while `inspect-ai` requires `aioboto3`, which caps
`boto3` below `1.40.62`. They cannot share a virtualenv. The plain `litellm` *library* coexists
fine, which is why the backend can still pin it — this was verified by resolution rather than
assumed, and `backend/tests/test_engine_coexistence.py` keeps it true.

## What keeps the "no provider assumptions" claim honest

- The submit form offers a **dropdown of gateway aliases**, never a free-text model field, so a
  provider-native string cannot be typed into a run.
- **Preflight runs a real completion for the subject and the judge** before any run starts.
- The eval subprocess is launched with **every provider credential stripped from its
  environment**, and each task's judge argument explicitly overridden. `inspect_evals` tasks
  default their graders to a hardcoded provider model, so without both of those a run would
  quietly bill a real provider. `backend/tests/test_env_scrubbing.py` asserts the scrubbing.
