# OmniCoach AI

Multi-sport AI training-plan generator (running first). A team of AI expert
agents proposes sessions; a human coach validates before the athlete sees them.

This repository holds the **code only**. Two things live outside it on purpose:

- **Your Python environment** (`.venv/`) — machine-specific, rebuilt per machine.
- **The workout library** (`omnicoach-backend/data/converted/`) — licensed
  *personal-use only*, shared separately, never committed.

Both are excluded by `.gitignore`.

## Repository layout

```
omnicoach/
├── omnicoach-app.html        ← the front-end (open in a browser)
├── omnicoach-backend/        ← the FastAPI server
│   ├── app/                  ← application code
│   ├── tests/                ← pytest suite (run with LLM_PROVIDER=mock)
│   ├── .env.example          ← copy to .env on each machine
│   ├── requirements.txt
│   ├── README.md             ← what the backend does & why
│   └── SETUP.md              ← full from-scratch setup (≈10 min)
└── FIXES.md                  ← changelog
```

## First time here?

Read **`omnicoach-backend/SETUP.md`** — it walks a fresh machine through Python,
the virtual environment, the workout library, and running both halves. About ten
minutes.

## Everyday workflow (Git)

See **`CONTRIBUTING.md`** for the day-to-day "pull → work → commit → push" loop
and how to avoid stepping on each other's changes.
