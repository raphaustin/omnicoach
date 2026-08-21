# OmniCoach AI

Multi-sport AI training-plan generator — **running first**. A team of AI expert
agents proposes training sessions; a human **coach** reviews and validates them
before the athlete sees the plan.

> Academic internship project. Running is fully implemented; cycling and
> swimming are planned but not built yet.

---

## How it works (in one minute)

- The running **agent** does not invent sessions. It **selects** from a library
  of **186 published running workouts** (80/20 polarised method). The LLM only
  picks a code from a constrained list, so it physically cannot hallucinate a
  session that doesn't exist.
- Session shortlisting (by training phase and session-length budget) is done in
  **deterministic Python**; the LLM only makes the final choice.
- A human **coach** generates a week for an athlete, can **swap / regenerate /
  edit / save** sessions, then **validates & releases** the plan to the athlete.
- Two halves talk over HTTP: a **FastAPI back-end** and a **single-file
  front-end** (`omnicoach-app.html`).

---

## ⚠️ Two things are NOT in this repository

Downloading the code is not enough to run it. On purpose, two things live
outside Git (both excluded by `.gitignore`):

1. **The workout library** — `omnicoach-backend/data/converted/`.
   The 186 sessions are licensed **personal-use only** by their provider, so
   they are never committed. **You must obtain them separately** (ask a
   teammate or the supervisor for `converted_explicit_zones_v1.zip`) and unzip
   their contents into `omnicoach-backend/data/converted/`.
   Without this, the server starts but **cannot generate anything** (you'll get
   a `503 Library not available`).

2. **The Python virtual environment** — `.venv/`.
   It contains machine-specific paths and is never shared; you rebuild it
   locally (below).

---

## Prerequisites

- **Python 3.12+**
- **A web browser** (Chrome, Edge, Firefox…)
- **[Ollama](https://ollama.com)** — for the free, local, offline LLM (the
  recommended default). Alternatively you can point the app at a hosted LLM, or
  run with no LLM at all (see *LLM providers* below).

---

## Setup (Windows / PowerShell)

Commands assume you are in the project's `omnicoach-backend/` folder unless
stated otherwise. macOS/Linux users: see the note at the end.

> Tip: keep the project **outside OneDrive** — OneDrive sync fights with
> `.venv/`. Something like `C:\dev\omnicoach` is ideal.

### 1. Add the workout library

Get `converted_explicit_zones_v1.zip` from a teammate/supervisor and unzip it so
that the JSON files land here:

```
omnicoach-backend/data/converted/*.json   (186 files + index.json)
```

### 2. Create the environment and install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Your prompt should now start with `(.venv)`.
If `Activate.ps1` is blocked by an execution-policy error, run
`Set-ExecutionPolicy -Scope Process -Bypass` once, then activate again.

### 3. Configure the LLM

Copy the template and adjust it:

```powershell
Copy-Item .env.example .env
```

The default block uses Ollama. For good results, use `qwen2.5:7b-instruct`
(edit `LLM_MODEL` in `.env` accordingly) and pull it once:

```powershell
ollama pull qwen2.5:7b-instruct
```

> **Gotcha:** if `LLM_MODEL` is missing from `.env`, the code falls back to a
> slower model (`qwen3:8b`) that can time out. Always set `LLM_MODEL` explicitly.

### 4. Run the back-end

```powershell
uvicorn app.main:app --reload
```

Leave this window open. In **another** window, check it:

```powershell
Invoke-RestMethod http://localhost:8000/health        # -> status ok + your model
Invoke-RestMethod http://localhost:8000/library/stats # -> 186 workouts
```

### 5. Open the front-end

Open **`omnicoach-app.html`** as a **local file** in your browser
(double-click, or right-click → Open with → browser).

> Do **not** open it inside a sandboxed preview (e.g. VS Code's built-in
> preview) — those block access to `localhost`. CORS is already open on the
> back-end, so a real browser tab talks to it directly.

---

## Using the app

Accounts are simulated in the page (real auth comes later). On the login screen:

- **Admin** — log in with `admin` / `admin`. Configure the agents; preview as
  Athlete or Coach.
- **Coach** — use the one-click demo login (Marc Lefèvre). This is the main view.
- **Athlete** — demo athletes (Sarah Jansen; Tomás Alves is self-service).

**Typical coach flow:**
1. Pick an athlete from the list (the panel then pre-fills that athlete's
   training days and notes).
2. **Generate the running week** — a live call to the agent.
3. On any session you can **Swap** (browse phase-appropriate sessions, or the
   whole library with search), **regenerate** it, **edit** its steps, or
   **💾 Save** it to the library. You can also **➕ Add a session** from scratch.
4. **Validate & release** to push the plan to the athlete.

---

## Running the tests

No LLM, key, or network needed — the mock provider makes the suite deterministic:

```powershell
$env:LLM_PROVIDER="mock"; pytest -q
```

Tests that need the workout library are skipped automatically when
`data/converted/` is absent, so a green run without the library is expected —
add the library (step 1) to run the full suite.

---

## LLM providers

Switching provider is an `.env` change, never a code change. Four modes
(details and examples in `.env.example`):

- **`ollama`** — free, local, offline. Recommended for development.
- **`openai_compat`** — any OpenAI-compatible endpoint (e.g. Google AI Studio
  free tier, Groq, OpenRouter; or paid Mistral/DeepSeek). Needs `LLM_API_KEY`.
- **`mock`** — no LLM at all; for tests, CI, and front-end work.

After **any** change to `.env`, restart uvicorn — the file is read only at
startup, and `--reload` reloads code, not `.env`.

---

## Troubleshooting

- **`503 Library not available`** → the workout library is missing; do step 1.
- **`/health` shows the wrong model** → `LLM_MODEL` not set or uvicorn not
  restarted after editing `.env`.
- **Generation stops working after you deleted a session** → deleting a JSON by
  hand leaves `index.json` out of sync. Rebuild it, then restart uvicorn:
  ```powershell
  python -c "from app.library.workout_library_reader import rebuild_index; print(rebuild_index('./data/converted')['session_count'])"
  ```
- **First generation is slow (30–60 s)** → the model is loading into memory;
  later calls are fast. Not a crash.
- **The page can't reach the back-end** → confirm uvicorn is running and the
  API base in the app matches `http://localhost:8000`.

---

## API reference (back-end)

| Method | Path | Purpose |
| ------ | ---- | ------- |
| GET  | `/health` | Provider + model actually loaded |
| GET  | `/library/stats` | Library size and families |
| GET  | `/athlete/pace-zones` | Personal paces from a reference performance |
| POST | `/agents/running/propose` | Generate a week (sessions expanded with paces) |
| POST | `/agents/running/alternatives` | Swap candidates (`all_sessions` = whole library) |
| POST | `/agents/running/regenerate-session` | Regenerate one day |
| POST | `/library/sessions` | Save / create a session in the library |
| GET  | `/library/custom-codes` | List user-created sessions |

Interactive docs while the server runs: <http://localhost:8000/docs>.

---

## Repository layout

```
omnicoach/
├── omnicoach-app.html        ← front-end (open in a browser)
├── omnicoach-backend/        ← FastAPI server
│   ├── app/                  ← application code
│   ├── tests/                ← pytest suite (LLM_PROVIDER=mock)
│   ├── data/converted/       ← workout library (NOT in Git — add it yourself)
│   ├── .env.example          ← copy to .env per machine
│   ├── requirements.txt
│   ├── README.md             ← what the back-end does & why
│   └── SETUP.md              ← detailed setup notes
├── CONTRIBUTING.md           ← day-to-day Git workflow (pull → commit → push)
├── FIXES.md                  ← changelog
└── README.md                 ← this file
```

---

## macOS / Linux notes

Same steps, different shell:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

---

## Data & license

The application code in this repository is the team's work. The workout library
(shared separately) is **licensed for personal use only** by its provider and is
deliberately kept out of the repository — do not commit it or redistribute it.
