# What was fixed

Your generation was stuck on `qwen3:8b` no matter what `.env` said. Root cause
found and fixed, plus two smaller bugs in the pace calculator.

## 1. The .env file was never being read  (the real problem)

`app/config.py` read settings with `os.getenv(...)`, but nothing ever loaded the
`.env` file into the environment. So every setting silently fell back to the
hard-coded default — including `LLM_MODEL` defaulting to `qwen3:8b`. Editing
`.env` changed nothing; only real shell variables were ever seen.

Fix: `config.py` now calls `load_dotenv(override=True)` before reading anything,
and `python-dotenv` was added to `requirements.txt`. Verified: `/health` now
reports exactly what `.env` says.

## 2. Duplicate `calculate_vdot` in pace_calculator.py

The method was defined twice; Python silently kept only the second and threw away
the first. Removed the dead one to avoid confusion. (The active behaviour is
unchanged.)

## 3. Line endings normalised

`pace_calculator.py` was saved with Windows CRLF endings; normalised to LF for
consistency with the rest of the codebase.

## Verified working

- 9/9 tests pass.
- `/health` reports the configured model.
- `/athlete/pace-zones` returns real zones (recovery 5:51/km, tempo 4:30/km, …
  for a 47:30 10 km).
- `/agents/running/propose` returns a valid week end-to-end (tested against a
  schema-honouring stand-in for Ollama).

## One reminder

After ANY change to `.env`, restart uvicorn (Ctrl+C, then relaunch). The file is
read once at startup — `--reload` only reloads code, not `.env`.

## To run

```powershell
cd omnicoach-backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt        # now includes python-dotenv
# put the library at data\converted  (see SETUP.md)
uvicorn app.main:app --reload
```

---

# v3 — session editing, athlete self-service, visual rework

## Coach can now edit a proposed week before validating
Two new back-end endpoints:
- `POST /agents/running/alternatives` — valid swap candidates for one day.
- `POST /agents/running/regenerate-session` — the agent redoes one day.

In the coach panel, every proposed session has **↔ Swap workout** (pick another
library code from a dropdown, each shown with its detail) and **↻ Ask agent to
redo** (the LLM re-picks that one day). Edits are kept in an editable proposal and
included when the coach validates. Both reuse the same schema-constrained
selection, so a swap or regen can still only ever land on a real workout code.

## Athletes without a coach generate their own plan
An athlete who signed up with "I want a coach" unchecked now gets a
**self-service panel** in their dashboard: one click calls the running agent
directly (same `/propose` endpoint) and the plan appears immediately, with no
coach gate. Demo account added: **Athlete solo — Tomás A.** (no coach).
Athletes with a coach keep the validated-plan flow.

## Visual rework of the generated plan
- Each session is now a card with a **zone bar** (how the session's time splits
  across Z1–Z5, colour-coded) and a **timeline** of steps with coloured dots.
- Per-step: role, zone label, duration/distance, and the athlete's target pace.
- Shared renderer (`sessionCard`) used by the coach editor, the athlete's
  coach-validated plan, and the self-service plan — one consistent look.

Still in-memory only: released and self-service plans live in the page. Plan
persistence with real states is the next back-end step.
