# OmniCoach — setup from scratch

Everything a new machine needs to run the current version. ~10 minutes.
Written for Windows / PowerShell (notes for Mac/Linux where it differs).

You will end up running two things:
- the **back-end** (a Python server that talks to the AI), and
- the **front-end** (`omnicoach-app.html`, opened in a browser).


## 0. What you received

- `omnicoach-backend/` — the server (this folder).
- `omnicoach-app.html` — the interface. Keep it anywhere; you'll double-click it later.

You did **not** receive two things, on purpose:
- **The workout library** (the 186 running sessions). It's licensed
  *personal-use only* by its provider, so it's shared separately, never inside
  the code. Ask a teammate for `converted_explicit_zones_v1.zip`.
- A Python environment. You build your own below — it's machine-specific.


## 1. Install the tools (once per machine)

- **Python 3.11+** — python.org/downloads. During install, tick
  **"Add Python to PATH"**.
- Check it worked, in a new PowerShell:
  ```powershell
  python --version
  ```


## 2. Set up the back-end

Open PowerShell **inside the `omnicoach-backend` folder** (Shift + right-click
the folder → "Open PowerShell window here"), then:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

> If `Activate.ps1` is blocked by a security policy, run this once, then retry:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

Mac/Linux equivalent of the venv lines:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && cp .env.example .env
```


## 3. Add the workout library

Unzip `converted_explicit_zones_v1.zip`. Dig in until you see a folder
containing files like `rci1.json` — that folder is the one you want.

```powershell
mkdir data
Copy-Item -Recurse "C:\path\to\converted" ".\data\converted"
```

Check it landed (should print a number near **186**):
```powershell
(Get-ChildItem .\data\converted\*.json).Count
```


## 4. Confirm everything is wired

```powershell
pytest -q
```
You want **`9 passed`** (green). If you see `9 skipped`, the library folder
isn't at `data\converted` — recheck step 3.


## 5. Run it

### The fast way first — no AI needed
`.env` ships with `LLM_PROVIDER=mock`, which returns instant fake answers. Good
for confirming the whole app works before installing anything else.

```powershell
uvicorn app.main:app --reload
```
Leave this window open (the server runs as long as it is).

- API test page: open <http://localhost:8000/docs>
- Full app: double-click `omnicoach-app.html`, log in with the **Coach** demo
  account, click **Connect**, then **Generate the running week**.

> The page must be opened as a local file in your browser. It talks to
> `http://localhost:8000` on your own machine.

### Then the real AI — free & local
1. Install **Ollama** from <https://ollama.com/download>.
2. Pull a model (≈5 GB, once):
   ```powershell
   ollama pull qwen2.5:3b
   ```
3. In `.env`, change one line to `LLM_PROVIDER=ollama`.
4. **Stop uvicorn (Ctrl+C) and start it again** — `.env` is only read on start.
5. Regenerate. The **first** generation can take 30–60 s (the model loads into
   memory); later ones are quick.


## Daily use (after the one-time setup)

```powershell
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```
…then open `omnicoach-app.html`.


## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `pytest` says `9 skipped` | Library missing → redo step 3 (`data\converted` full of `.json`). |
| "The model could not be reached" | You're on `ollama` but Ollama isn't installed/running. Install it, or set `LLM_PROVIDER=mock` and restart uvicorn. |
| "Cannot reach the back-end" in the app | uvicorn isn't running, or the app is open inside a sandboxed preview. Run uvicorn; open the `.html` as a real local file. |
| `Activate.ps1 cannot be loaded` | Run the `Set-ExecutionPolicy` line in step 2. |
| `uvicorn` / `pytest` not recognised | The venv isn't active. Run `.venv\Scripts\Activate.ps1` first. |

## What's here and what isn't

Working now: the running agent (selects from the 186-session library), the
provider-agnostic LLM layer (mock / ollama / any OpenAI-compatible API), the
coach view wired to the live API.

Not built yet: cycling & swimming agents, the coordinator, accounts/auth, plan
persistence and the coach validation endpoint, the 80/20-zones → VDOT/CSS
mapping. See `README.md` for the details.
