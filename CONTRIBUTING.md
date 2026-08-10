# Working together with Git (for two people, new to Git)

This is the whole workflow. If you follow the golden rules, you will almost never
hit a conflict. We use **GitHub Desktop** (the app with buttons), so there are no
commands to memorise.

---

## The mental model in one picture

```
  Your PC                     GitHub (the cloud)                Nathan's PC
  ───────                     ──────────────────                ───────────
  edit files                                                    edit files
     │                                                             │
     │  Commit  (save a labelled snapshot, locally)                │
     ▼                                                             ▼
  Push  ───────────────►   the shared repo   ◄───────────────  Push
                                  │
  Pull  ◄───────────────────────┘└──────────────────────────►  Pull
  (download the other person's latest work before you start)
```

- **Commit** = "save a snapshot with a label", on your machine only.
- **Push**   = "upload my commits to GitHub" so the other can get them.
- **Pull**   = "download the other person's commits" onto my machine.

---

## The 3 golden rules (this is what prevents pain)

1. **Pull before you start.** Every time you sit down to work, open GitHub Desktop
   and click **Fetch origin → Pull** first. You start from the latest version.

2. **Commit small and often, push when you pause.** Finished a bit that works?
   Commit it with a short message ("fix pace zones for named distances"), then
   Push. Small commits are easy to understand and easy to undo.

3. **Don't both edit the same file at the same time.** Agree who's touching
   `omnicoach-app.html` vs the backend today. Two people editing the same lines is
   the #1 cause of conflicts. A quick "I'm on the front-end this afternoon" message
   avoids 95% of them.

---

## Your everyday loop

1. Open **GitHub Desktop**.
2. **Fetch origin**, then **Pull** if it shows incoming changes.
3. Do your work in your editor. Test it.
4. Back in GitHub Desktop: review the changed files on the left, write a short
   **Summary**, click **Commit to main**.
5. Click **Push origin**.

That's it. Repeat.

---

## Never commit these (already handled by `.gitignore`)

- `.venv/` — your Python environment. Rebuilt per machine, never shared.
- `.env` — your local settings. Each of you copies `.env.example` → `.env`.
- `data/` — the licensed workout library. Shared separately, never in the repo.

GitHub Desktop already hides them because of `.gitignore`. If you ever see
`.venv` or `data` in the list of changes, **stop** — something's off, ask before
committing.

---

## If you hit a conflict anyway

It's not scary. A conflict just means you both changed the same lines and Git
wants a human to choose. GitHub Desktop will tell you which file. Open it: you'll
see both versions marked. Keep the right lines, delete the conflict markers
(`<<<<<<<`, `=======`, `>>>>>>>`), save, then commit. If in doubt, message each
other and decide together — nothing is lost, both versions are still there.

---

## One-time setup per machine

1. Install **Git**: https://git-scm.com/download/win (accept all defaults).
2. Install **GitHub Desktop**: https://desktop.github.com — sign in with your
   GitHub account.
3. **Clone** the repo: GitHub Desktop → *File → Clone repository* → pick
   `omnicoach` → choose a folder **outside OneDrive** (OneDrive + `.venv` = sync
   trouble). Done.
4. Then follow `omnicoach-backend/SETUP.md` to build the `.venv` and add the
   library.
