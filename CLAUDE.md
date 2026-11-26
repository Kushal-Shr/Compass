# Compass

Compass is a personal planner agent for one student. It pulls Canvas, Google Calendar, Outlook and internship data into SQLite, builds a daily study plan, writes a morning brief, and exposes the plan to Claude Projects (one per subject) through an MCP connector. Compass plans; the Claude Projects mentor.

The plan is in `plan/`. `plan/README.md` has the decisions and phases. Each phase folder has a `README.md` checklist and one `step-NN-*.md` file per feature.

The architecture is in `docs/architecture.md`: package layers and what each may import, core interfaces, data ownership, and decisions D1–D7. Follow it when building a step. If a step conflicts with it, say so before building.

Current status, file map and open issues (read this instead of re-reviewing the repo):
@CONTEXT.md

Keep `CONTEXT.md` current. After any change that affects status, structure, decisions, known issues or open questions (not only plan steps), update the matching section before you finish. Keep it short and replace stale lines, don't append history. A Stop hook (`.claude/hooks/context-check.sh`) sends you back once if tracked files changed but `CONTEXT.md` didn't.

## Building a plan step

When asked to do a step (for example "do step 1.4" or "build plan/phase-1-planner-and-brief/step-04-estimate.md"):

1. Read the step file and its phase `README.md`.
2. Check that the steps before it are ticked in the phase `README.md`. If one isn't, say so and ask before going on.
3. Read the files the step lists under "Read first".
4. Build only what the step describes. If something outside the step must change, keep it minimal and mention it.
5. Write the tests the step lists, then run the whole suite with `.venv/bin/pytest`.
6. Check every line under "Done when".
7. Tick the step in the phase `README.md`, and update the Status section of `CONTEXT.md` (and any issue or decision the step settled).
8. Report what changed, any decision you made, and anything the user has to do. Then stop. Don't start the next step, and don't commit unless asked.

If a step says **You do**, those are tasks only the user can do (accounts, logins, settings). Walk the user through them and wait.

## Conventions
- Python 3.12, pydantic v2, stdlib `sqlite3`, pytest. The virtualenv is `.venv/`. Install with `.venv/bin/pip install -e ".[dev]"`.
- Package layout: `compass/connectors/` (fetch data), `compass/engine/` (pure logic), `compass/agents/` (Claude calls), `compass/outputs/` (briefs, dashboard), `compass/mcp/` (connector server).
- Datetimes are timezone-aware. Convert to the `timezone` in `config.yaml` at the edges (connectors), and never compare naive and aware datetimes.
- Settings come from `compass/config.py`. Don't read `config.yaml` or environment variables anywhere else.
- Task IDs are source-prefixed: `canvas:123`, `outlook:abc`, `job:greenhouse:456`.

## Rules
- Code does the math (dates, slots, scores, filters). Claude does the language (reading, writing, judging fit). Don't ask the model to do arithmetic or scheduling.
- Every Claude API call goes through `compass/agents/llm.py`.
- Read-only by default. Compass never sends email to anyone but the user, never submits applications or assignments, and never edits calendar events it didn't create.
- Every feature works with `--demo` on fake data, with no accounts.
- Tests never touch the network. Connectors are tested against saved fixtures in `tests/fixtures/` with names, emails and IDs scrubbed.
- Never print, log or put secrets in prompts. Don't echo the contents of `.env`, `credentials.json`, `token.json` or any `client_secret_*.json`.
- Mentoring help explains, plans and reviews. It never writes graded work.
- Course files and personal data never go in git.
