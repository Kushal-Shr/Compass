# Compass: project context

This file is loaded at the start of every chat through `CLAUDE.md`, so new chats don't need to re-review the repo. Trust it for orientation. Read the files it names only when the task needs them. Keep it short and current. When a step is finished, update **Status** and anything else that changed.

## Status (updated 2026-11-26)
- **Built:** `compass/models.py`, `compass/store.py`, `compass/config.py` (1.1), `compass/demo.py` (1.2), `compass/engine/merge.py` (1.3), `compass/engine/estimate.py` and `compass/orchestrator.py` (1.4), `compass/engine/priority.py` (1.5), `compass/engine/freetime.py` (1.6), `compass/engine/planner.py` (1.7), `compass/engine/warnings.py` (1.8), and from 1.9 `compass/connectors/{base,demo}.py`, `compass/outputs/brief.py`, `compass/cli.py` and the full `orchestrator.py`; `compass/connectors/canvas.py`, `scripts/capture_canvas_fixture.py` and `compass canvas-check` (1.10). 156 tests passing. `compass brief|plan|tasks|estimate --demo` all work after `pip install -e ".[dev]"`.
- **Ticked steps:** phase 0, 1.1–1.10 (the demo pipeline and the Canvas connector). Next up is **step 1.11** (Google Calendar connector). `canvas-check` was confirmed by the user (10 active courses), and the captured fixture was reviewed and is clean.
- **Demo data:** `DEMO_TODAY` is Mon 2026-11-30 07:00 America/Chicago. `DEMO_TZ` is hardcoded, not read from config, so demo output never changes. 10 tasks across 4 generic courses (IDs `demo:101`–`demo:110`). `demo:102` is overdue, `demo:101` is due tonight, `demo:103` is submitted, and `demo:110` is the 200-point project. `demo_tasks()` leaves `est_minutes` at 0, like a real source. Events: MWF and TTh classes for 14 days, plus 3 one-offs. The Tue 17:30–18:30 study group overlaps dinner.
- **Config:** `load_config()` returns a frozen `Config` that rejects unknown keys (`extra="forbid"`), so new `config.yaml` sections such as `budgets:` need a model field first. Times must be quoted `"HH:MM"`, because PyYAML reads an unquoted `18:00` as the number 1080. `load_env(path, environ=None)` reads `.env`, and real environment variables override it (needed for Actions). `Secrets.canvas_token` and `anthropic_api_key` are `SecretStr`, read with `.get_secret_value()`.
- **Store and merge:** times are stored as UTC ISO strings and read back as aware UTC datetimes. Naive datetimes raise `ValueError`. Schema changes go in `store.MIGRATIONS` (append only; `PRAGMA user_version` tracks them; 1 = `tasks.missing`). `upsert_task(task, now)` and `log_run(workflow, started, finished, status)` now take their times; the store never reads the clock. `merge_tasks(store, source, tasks, now, window)` marks a task missing only if it wasn't fetched, isn't submitted, isn't past due, and is due inside `window`. Undated tasks are never marked missing. `mark_missing` returns `None` if the task is already missing.
- **Estimates:** manual estimates are append-only rows in `estimate_overrides` (D5, migration 2). `set_estimate(task_id, minutes, now)` adds a row, `get_overrides()` returns the latest per task, and `get_tasks()` puts the override in `est_minutes`. `tasks.est_override` is left over from version 0 and no longer read. `engine/estimate.py` is pure: the keyword in the title's head (before `:`) sets the base, and the last keyword wins ("Reading Quiz" is a quiz). Points above the course median (0-point tasks ignored) scale it up, capped at 2×. `orchestrator.apply_estimates(store)` writes the results, keeping the engine store-free (the user chose this over the step's `engine/` placement).
- **Priority:** `score(task, now)` = urgency (100 × 0.5^(hours/24)) + 1000 if overdue and unsubmitted + 2·ln(1+points) + 50 × min(remaining/time left, 1). Weights are constants in `engine/priority.py`. `rank` drops submitted, missing and zero-remaining tasks (so run estimates first), puts undated tasks after all dated ones, then sorts by score, due date and ID.
- **Free time:** `busy_blocks`, `free_gaps(day, events, config, not_before=None)` and `free_minutes` all return local (`config.tz`) times. Events are clipped to the day window, so ones spanning midnight count on both days. `busy=False` events never block. All-day events block the whole window only if busy, and their end date is exclusive. Only overlapping blocks merge (into `fixed` if any part is an event, with titles joined by ` + `); touching ones stay separate. `Event.all_day` and `Event.busy` were added in 1.6 (migration 3), earlier than planned. Step 1.11 should set `busy` from Google's `transparency` and keep free all-day events instead of skipping them.
- **Planner:** `plan_day(day, tasks, events, config, now)` places tasks due tonight first, then the rest in `rank` order. Each task asks for a daily share (`daily_share`): all remaining minutes if due today or overdue, remaining ÷ days before the due date otherwise (the due day is left as a buffer), and one max block if undated. Shares are at least one minimum block. Blocks start on 5-minute marks, end by the task's due time, avoid leftovers shorter than a minimum block (100 → 75 + 25), and each is followed by a break, shortened if the gap ends first. The plan stores busy, study and break blocks. `save_plan`/`get_plan` use `plans.title` and a new `plan_unplaced` table (migration 4).
- **Warnings:** `check(tasks, events, config, now, days=14)` returns `Warning(kind, date, task_id, message)`, sorted by date, then kind (overdue, missing, cannot_finish, overloaded_day), then task ID. Usable time is free minutes capped at the daily cap. `overloaded_day` is a running total: work is paced like the planner (spread over the days before the due date) and compared with usable time up to each day, so earlier free time absorbs later load. It gives one warning per run of overloaded days, with no `task_id`. Missing tasks get `missing` only, never `overdue`. On the demo week the only warning is `demo:102` overdue.
- **Morning run:** `orchestrator.refresh(sources, store, config, now)` fetches in threads over a window of now − 7 days to now + 14 days. On the main thread it merges only sources that succeeded (D3), then estimates, plans today (saved), and checks warnings. `morning(..., brief_dir="briefs", clock=None)` also renders and saves `briefs/YYYY-MM-DD.md` and logs one `runs` row (`ok`, `partial` or `failed`). "What changed" is the changes returned by this run's merge. Events are replaced per source (`replace_events(events, source=)` deletes only IDs starting `source:`). Source exceptions become `SourceResult.error`, cut to 200 characters. Connectors must keep secrets out of exception text. Demo briefs go to `briefs/demo/` so they never overwrite a real brief for the same date. Real (non-demo) commands print "Not connected yet" and exit 1. The CLI needs to run from the repo folder (it reads `./config.yaml`).
- **Canvas:** `CanvasSource(base_url, token, tz, session=None, sleep=time.sleep)`. It fetches active courses, then every assignment per course (`include[]=submission`, no `bucket`), and keeps the ones due inside the fetch window. `last_stats` counts undated, outside-window and skipped courses. Submitted means `workflow_state` in submitted/graded/pending_review, or `submitted_at`, or excused. Course is `course_code`. A 403/404 on one course skips it. It needs https, sends the token only in the header, and refuses pagination to another host. 401 gives `TOKEN_HELP`. Timeouts are (10, 30); one retry on 5xx or timeout. The fixture script allows only fake patterns (`Course N`, `FAKE N`, `Assignment N`, example.edu URLs), Canvas vocabulary values and timestamps in its output, and refuses on your host or an email. A substring search for real names gave false refusals on generic titles. Tests use `tests/fixtures/canvas/synthetic.json` (hand-made: pagination, excused, DST, 403) and `captured.json` (the user's real responses, scrubbed and reviewed 2026-11-26: 10 courses, 107 assignments, one page each, due dates from 2024-09 to 2026-12, so some "active" courses are old terms, which the window filters out). Not wired into `compass brief` yet (1.12).
- **Repo is public** by the user's choice (2026-11-25). Everything tracked, including `config.yaml` and commit author emails, is visible.
- **Secrets guard:** gitleaks runs as a `pre-commit` hook (`.pre-commit-config.yaml`, gitleaks v8.30.0). Each new clone needs `.venv/bin/pre-commit install`. Fake secrets in tests and fixtures must look non-random (e.g. `"fakefakefakefake"`), or gitleaks' generic-api-key rule blocks the commit.
- **Not built yet:** the real connectors (Canvas 1.10, Google Calendar 1.11), `agents/` (`llm.py` 1.13, writer 1.14), `views.py` (2.2), `mcp/`, the dashboard.
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
- **D1:** `pyproject.toml` finds packages automatically. Not done in 1.9 (the current list covers everything so far). **Step 2.1 needs it or an edited list**, because `compass/mcp` isn't in the list.
- **D2 (accepted, built in 1.3):** SQLite stores UTC, and the code uses timezone-aware datetimes.
- **D3 (accepted, built in 1.3 and 1.9):** A source that errored is never merged. Tasks are marked missing only inside the fetched window.
- **D4:** `views.py` is the shared read layer for the brief, MCP and the dashboard. Step 2.2.
- **D5 (accepted; `estimate_overrides` built in 1.4):** User data is stored as append-only rows with UUIDs (`progress`, `estimate_overrides`, `application_events`, `habit_log`), and sync carries all of them. Steps 3.3 and 4.8 still to come.
- **D6:** The write gate is built at step 4.6, not 7.1.
- **D7:** Only MCP tools named `log_*` write, and only to append-only tables.

The step files in `plan/` don't reflect D1–D7 yet. If a step conflicts with one, say so before building.

## Known issues in current code (fix in the step noted)
- `Event` has no `calendar_id` field (7.2).
- Canvas assignments with no online submission (`on_paper`, `none`) can never show as submitted, so they'll be flagged overdue after their due date. The real data has 6 `on_paper` assignments. Revisit after the shadow week (3.7) if it's noisy.
- The Python 3.14 venv doesn't match the 3.12 convention.
- The repo is public, so the phase 3 `state` branch (the database on Actions) can't live in it, and public Actions logs and artifacts must never contain personal data. Decide before phase 3: a separate private state repo (recommended) or an encrypted database.
- The Google OAuth app may be in "Testing" status, where refresh tokens expire after 7 days. That would break unattended runs in phase 3. Check it, or publish the app, before phase 3.
- `config.yaml` is public and its protected-time titles are personal. A git-ignored local override would fix this if the user wants it.

## Open questions for the user
- Accept D1, D4, D6 and D7?
- Internship roles are answered (SWE, data, AI/ML, full stack, DevOps; anywhere in the US). Still open for step 2.4: eligibility (internship / co-op / new grad) and visa sponsorship.
- Where does Actions state live, given the public repo? Needed before phase 3.
- Which internship season to target after Apr 30, 2027? Needed for step 4.9.
