# OmniCoach — back-end (vertical slice)

One agent, one real LLM call, end to end. **Runs on €0.**

This is Phase 2 of the plan: prove the whole chain works before adding the other
two sports, the coordinator, the accounts and the coach validation.

## What it does

`POST /agents/running/propose` takes an athlete diagnosis and returns one week of
running sessions **selected from the supervisor's 186-workout canonical library** —
never invented.

```
Athlete context ──► shortlist (pure Python, no LLM)
                       │  filters the 186 workouts by phase + session budget
                       ▼
                    ~90 candidates ──► LLM picks one per day ──► validated proposal
                       (~25 tokens each)     (schema-constrained)
```

## Why the agent selects instead of generates

The library ships sessions that are already validated, traceable and
physiologically coherent. So the agent picks a code and justifies it. That buys
three things:

1. **No hallucinated physiology** — the sessions pre-exist.
2. **Verifiable output** — a code either exists or it does not.
3. **A free model is enough** — the prompt is a ~90-line catalog, not 8k of JSON
   per workout.

## The correctness trick

The JSON schema sent to the model contains an `enum` of the shortlisted codes:

```python
"workout_code": {"type": "string", "enum": ["RF1", "RAe3", "RL7", ...]}
```

Both back-ends honour it by **constraining the decoder** — Ollama's `format`
parameter and the OpenAI-compatible `response_format: json_schema`. Tokens that
would break the schema cannot be sampled, so the model *physically cannot*
invent a workout that does not exist. This removes the single biggest risk we
identified for the agent pipeline (malformed or hallucinated JSON hand-offs).

We still verify the codes in Python afterwards. Never trust, always verify.

## Run it free

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # defaults to free local Ollama

# Point at the library (not bundled — personal-use licence)
mkdir -p data && ln -s /path/to/converted_explicit_zones_v1/converted data/converted

# Option A — free, local, unlimited (recommended for development)
#   install from ollama.com, then:
ollama pull qwen2.5:3b && ollama serve

uvicorn app.main:app --reload
```

Then open <http://localhost:8000/docs>.

### Three ways to run, all free

| Mode | Setup | Limits | Use for |
|---|---|---|---|
| `ollama` | Install Ollama, pull a model | None. Unlimited runs, offline, data never leaves the machine | Daily development, the thousands of iterations |
| `openai_compat` + Gemini | Free key at ai.google.dev, no card | ~1,500 req/day, 15 req/min. Free-tier prompts may be used by Google for training | Checking the code works against a real hosted API |
| `mock` | Nothing | None | Tests, CI, front-end work with zero setup |

Switching to a paid provider later is an `.env` change — the code never moves.

## Test

```bash
LLM_PROVIDER=mock LIBRARY_PATH=./data/converted pytest -q     # 9 passed
```

The suite runs with no LLM, no key and no network.

## A bug found in the library reader

`WorkoutLibrary.search()` computes `duration_min = duration_sec / 60`. The 28
distance-based workouts — **all the long-run families** (RL, RLFF, RLMS, RLSP) —
carry `known_duration_sec = 0`, so they satisfy *any* `max_duration_min` filter.

Concretely: `search(max_duration_min=20)` returns a **32 km long run**.

`Catalog.search()` fixes this without touching the supervisor's reader: duration
filters exclude unknown-duration workouts, and the long-run families are filtered
by `max_distance_km` instead. Converting a time budget into a distance budget
needs a pace, so `AthleteContext.easy_pace_min_per_km` (default 6.0) makes that
assumption explicit rather than hidden. Two regression tests pin the behaviour.

## Layout

```
app/
  config.py              settings — provider is configuration, never code
  schemas.py             the API contract (frozen shape for the front-end)
  llm/provider.py        ollama | openai_compat | mock, all schema-constrained
  library/catalog.py     compact catalog + the duration-filter fix
  library/workout_library_reader.py   (supplied by the supervisor)
  agents/running.py      the selector agent
  main.py                FastAPI
tests/
```

## Not done yet, on purpose

Cycling and swimming agents · the coordinator · accounts and auth · plan
persistence and states (`draft → pending → validated`) · the coach validation
loop · the 80/20-zones → VDOT/Critical-Speed mapping (still an open question for
the supervisor — the sessions are not prescribable to a real athlete without it).
