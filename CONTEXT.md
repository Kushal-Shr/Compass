# Compass: project context

This file is loaded at the start of every chat through `CLAUDE.md`, so new chats don't need to re-review the repo. Trust it for orientation. Read the files it names only when the task needs them. Keep it short and current. When a step is finished, update **Status** and anything else that changed.

## Status (updated 2026-11-26)
- **Built:** `compass/models.py`, `compass/store.py`, `compass/config.py` (1.1), `compass/demo.py` (1.2), `compass/engine/merge.py` (1.3), `compass/engine/estimate.py` and `compass/orchestrator.py` (1.4). 65 tests passing.
- **Ticked steps:** phase 0, 1.1–1.4. Next up is **step 1.5** (priority scores). Leftovers from 0.2: the Outlook sign-in test (before phase 5); confirming Claude Desktop is installed (before phase 2).
- **Demo data:** `DEMO_TODAY` is Mon 2026-11-30 07:00 America/Chicago. `DEMO_TZ` is hardcoded, not read from config, so demo output never changes. 10 tasks across 4 generic courses (IDs `demo:101`–`demo:110`). `demo:102` is overdue, `demo:101` is due tonight, `demo:103` is submitted, and `demo:110` is the 200-point project. `demo_tasks()` leaves `est_minutes` at 0, like a real source. Events: MWF and TTh classes for 14 days, plus 3 one-offs. The Tue 17:30–18:30 study group overlaps dinner.
- **Config:** `load_config()` returns a frozen `Config` that rejects unknown keys (`extra="forbid"`), so new `config.yaml` sections such as `budgets:` need a model field first. Times must be quoted `"HH:MM"`, because PyYAML reads an unquoted `18:00` as the number 1080. `load_env(path, environ=None)` reads `.env`, and real environment variables override it (needed for Actions). `Secrets.canvas_token` and `anthropic_api_key` are `SecretStr`, read with `.get_secret_value()`.
- **Store and merge:** times are stored as UTC ISO strings and read back as aware UTC datetimes. Naive datetimes raise `ValueError`. Schema changes go in `store.MIGRATIONS` (append only; `PRAGMA user_version` tracks them; 1 = `tasks.missing`). `upsert_task(task, now)` and `log_run(workflow, started, finished, status)` now take their times; the store never reads the clock. `merge_tasks(store, source, tasks, now, window)` marks a task missing only if it wasn't fetched, isn't submitted, isn't past due, and is due inside `window`. Undated tasks are never marked missing. `mark_missing` returns `None` if the task is already missing.
- **Estimates:** manual estimates are append-only rows in `estimate_overrides` (D5, migration 2). `set_estimate(task_id, minutes, now)` adds a row, `get_overrides()` returns the latest per task, and `get_tasks()` puts the override in `est_minutes`. `tasks.est_override` is left over from version 0 and no longer read. `engine/estimate.py` is pure: the keyword in the title's head (before `:`) sets the base, and the last keyword wins ("Reading Quiz" is a quiz). Points above the course median (0-point tasks ignored) scale it up, capped at 2×. `orchestrator.apply_estimates(store)` writes the results, keeping the engine store-free (the user chose this over the step's `engine/` placement).
- **Repo is public** by the user's choice (2026-11-25). Everything tracked, including `config.yaml` and commit author emails, is visible.
- **Secrets guard:** gitleaks runs as a `pre-commit` hook (`.pre-commit-config.yaml`, gitleaks v8.30.0). Each new clone needs `.venv/bin/pre-commit install`. Fake secrets in tests and fixtures must look non-random (e.g. `"fakefakefakefake"`), or gitleaks' generic-api-key rule blocks the commit.
- **Not built yet:** `compass/cli.py` (the `compass` entry point in `pyproject.toml` doesn't work yet), every connector, engine, agent and output module.
- **Docs:** `docs/architecture.md` (layers, contracts, data ownership, decisions D1–D7). There are three SVG diagrams in `docs/diagrams/`: system design, UML class, and the morning-run sequence.
- **Environment:** `.venv` runs Python 3.14, but the convention and CI target 3.12.

## Where things are
| Path | What | In git |
|---|---|---|
| `CLAUDE.md` | How to build a step, conventions, rules | yes |
| `docs/architecture.md` | Architecture. Read the relevant section, not the whole file | yes |
| `plan/README.md` | Phases, dates, decisions, risks | **no** (ignored) |
| `plan/phase-N-*/README.md` | Phase checklist | **no** |
| `plan/phase-N-*/step-NN-*.md` | One feature per file, written as a prompt | **no** |
| `config.yaml` | Day window, protected time, planner limits, calendars, models | yes |
| `.pre-commit-config.yaml` | gitleaks secret scan on every commit | yes |
| `.claude/settings.json`, `.claude/hooks/context-check.sh` | Stop hook that sends Claude back if tracked files changed without a CONTEXT.md update | yes |
| `PLAN.md` | Just a pointer to `plan/`. Skip it | no |
| `Compass Project Plan.docx` | The original design, replaced by `plan/`. Skip it | no |

**Never open:** `.env`, `client_secret_*.json`, `credentials.json`, `token.json`.

## Architecture in brief
- Layers, from top to bottom: entry points (`cli`, `mcp/server`, `outputs/dashboard`) → `orchestrator.py` (workflows) → `views.py` (shared reads) and `outputs/brief.py` → `actions/` (writes outside Compass, all through `gate.py`) → `agents/` (all Claude calls through `llm.py`) → `connectors/` (fetch only, never touch the store) → `engine/` (pure functions, no I/O, no `datetime.now()`) → `store.py` (the only module that writes SQL) → `models.py` / `config.py` / `demo.py`. Code only imports from layers below it.
- `now`, `Config` and `Secrets` are passed in. Only entry points read the clock or load settings.
- All sources return one `SourceResult(source, tasks, events, jobs, emails, error)`. Sources are fetched in threads and merged on the main thread.
- Agents follow one pattern: code prepares the input, `llm.call` makes the call, code checks the output, and there's a fallback.
- Everything scheduled is a `compass <command>`. Hosting goes laptop (phases 1–2) → GitHub Actions plus a `state` branch (phases 3–5) → server (phases 6–9).

## Decisions D1–D7 (from architecture.md; D2, D3 and D5 accepted 2026-11-26, the rest still proposed)
- **D1:** `pyproject.toml` finds packages automatically. Step 1.9 or 2.1.
- **D2 (accepted, built in 1.3):** SQLite stores UTC, and the code uses timezone-aware datetimes.
- **D3 (accepted):** A source that errored is never merged (the caller's job, in 1.9). Tasks are marked missing only inside the fetched window (built in 1.3).
- **D4:** `views.py` is the shared read layer for the brief, MCP and the dashboard. Step 2.2.
- **D5 (accepted; `estimate_overrides` built in 1.4):** User data is stored as append-only rows with UUIDs (`progress`, `estimate_overrides`, `application_events`, `habit_log`), and sync carries all of them. Steps 3.3 and 4.8 still to come.
- **D6:** The write gate is built at step 4.6, not 7.1.
- **D7:** Only MCP tools named `log_*` write, and only to append-only tables.

The step files in `plan/` don't reflect D1–D7 yet. If a step conflicts with one, say so before building.

## Known issues in current code (fix in the step noted)
- The `plans` table has no title or course columns, so the 1.7 round-trip test will fail. Fix in step 1.7.
- `Event` has no `all_day` field (1.11) or `calendar_id` field (7.2).
- `replace_events` wipes every source's events. Once there's a second calendar source (Outlook, phase 5), a failed fetch from one would drop its events. Make it per-source then.
- Step 1.10 uses Canvas `bucket=upcoming`, which may only cover about a week. Check this in 1.10; `bucket=future` may be the right one.
- The Python 3.14 venv doesn't match the 3.12 convention.
- The repo is public, so the phase 3 `state` branch (the database on Actions) can't live in it, and public Actions logs and artifacts must never contain personal data. Decide before phase 3: a separate private state repo (recommended) or an encrypted database.
- The Google OAuth app may be in "Testing" status, where refresh tokens expire after 7 days. That would break unattended runs in phase 3. Check it, or publish the app, before phase 3.
- `config.yaml` is public and its protected-time titles are personal. A git-ignored local override would fix this if the user wants it.

## Open questions for the user
- Accept D1, D4, D6 and D7?
- Internship roles are answered (SWE, data, AI/ML, full stack, DevOps; anywhere in the US). Still open for step 2.4: eligibility (internship / co-op / new grad) and visa sponsorship.
- Where does Actions state live, given the public repo? Needed before phase 3.
- Which internship season to target after Apr 30, 2027? Needed for step 4.9.
