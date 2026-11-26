# Compass: project context

This file is loaded at the start of every chat through `CLAUDE.md`, so new chats don't need to re-review the repo. Trust it for orientation. Read the files it names only when the task needs them. Keep it short and current. When a step is finished, update **Status** and anything else that changed.

## Status (updated 2026-11-25)
- **Built:** the phase 0 skeleton only. `compass/models.py`, `compass/store.py`, empty package folders, `tests/test_store.py` (4 tests, passing).
- **Ticked steps:** 0.1 and 0.2, so **phase 0 is done**. Next up is **step 1.1** (config). Leftovers from 0.2: the Outlook sign-in test (before phase 5); confirming Claude Desktop is installed (before phase 2).
- **Repo is public** by the user's choice (2026-11-25). Everything tracked, including `config.yaml` and commit author emails, is visible.
- **Secrets guard:** gitleaks runs as a `pre-commit` hook (`.pre-commit-config.yaml`, gitleaks v8.30.0). Each new clone needs `.venv/bin/pre-commit install`.
- **Not built yet:** `compass/config.py`, `compass/cli.py` (the `compass` entry point in `pyproject.toml` doesn't work yet), every connector, engine, agent and output module.
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

## Decisions D1–D7 (proposed in architecture.md; the user hasn't approved them yet)
- **D1:** `pyproject.toml` finds packages automatically. Step 1.9 or 2.1.
- **D2:** SQLite stores UTC, and the code uses timezone-aware datetimes. Step 1.3.
- **D3:** A source that errored is never merged. Tasks are marked missing only inside the fetched window. Steps 1.3 and 1.9.
- **D4:** `views.py` is the shared read layer for the brief, MCP and the dashboard. Step 2.2.
- **D5:** User data is stored as append-only rows with UUIDs (`progress`, `estimate_overrides`, `application_events`, `habit_log`), and sync carries all of them. Steps 1.4, 3.3 and 4.8.
- **D6:** The write gate is built at step 4.6, not 7.1.
- **D7:** Only MCP tools named `log_*` write, and only to append-only tables.

The step files in `plan/` don't reflect D1–D7 yet. If a step conflicts with one, say so before building.

## Known issues in current code (fix in the step noted)
- `store.py` calls `datetime.now()` without a timezone, and `tests/test_store.py` uses timezone-less datetimes. Fix in step 1.3.
- The `plans` table has no title or course columns, so the 1.7 round-trip test will fail. Fix in step 1.7.
- `Task` has no `missing` field (fix in 1.3). `Event` has no `all_day` field (1.11) or `calendar_id` field (7.2).
- Step 1.10 uses Canvas `bucket=upcoming`, which may only cover about a week. Check this in 1.10; `bucket=future` may be the right one.
- The Python 3.14 venv doesn't match the 3.12 convention.
- The repo is public, so the phase 3 `state` branch (the database on Actions) can't live in it, and public Actions logs and artifacts must never contain personal data. Decide before phase 3: a separate private state repo (recommended) or an encrypted database.
- The Google OAuth app may be in "Testing" status, where refresh tokens expire after 7 days. That would break unattended runs in phase 3. Check it, or publish the app, before phase 3.
- `config.yaml` is public and its protected-time titles are personal. A git-ignored local override would fix this if the user wants it.

## Open questions for the user
- Accept D1–D7?
- Internship roles are answered (SWE, data, AI/ML, full stack, DevOps; anywhere in the US). Still open for step 2.4: eligibility (internship / co-op / new grad) and visa sponsorship.
- Where does Actions state live, given the public repo? Needed before phase 3.
- Which internship season to target after Apr 30, 2027? Needed for step 4.9.
