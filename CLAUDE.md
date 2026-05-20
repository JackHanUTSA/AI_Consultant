# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python CLI chat agent that conducts admissions consulting conversations with students, persists each case to SQLite + a per-student folder, and produces Markdown deliverables (profile summary, 4-school shortlist, per-school checklists, personal-statement draft).

## Run

```
python main.py
```

Requires `ANTHROPIC_API_KEY` in `.env` or the environment. The student is resolved by name on every run; entering the same name resumes the case from `consultant.db`.

## Architecture

A standard Anthropic tool-use loop. Files in dependency order:

1. `main.py` — boots SQLite, prompts for student name, loads-or-creates the row, hands off to `ConsultantAgent`.
2. `consultant/agent.py` — owns the message list. `_run_turn()` may iterate multiple times when the model wants tools; it exits the inner loop only when `stop_reason != "tool_use"`. After every turn it persists both the conversation and the profile to the DB.
3. `consultant/tools.py` — defines the tools and the dispatcher. Profile/artifact tools: `update_profile`, `save_artifact`, `list_artifacts`, `read_artifact`. University-knowledge-base tools: `list_universities`, `search_universities`, `get_university`. `update_profile` does a shallow per-key merge so nested objects (`academics`, `test_scores`, …) accumulate rather than overwrite.
4. `consultant/prompts.py` — the single source of truth for agent behavior: conversation style, what to learn, when to produce the four deliverables. **This is the file to edit when the agent asks weak questions or jumps to recommendations too early.**
5. `consultant/universities.py` — local cache + index over the goal-kicker top-100 US universities knowledge base (https://github.com/JackHanUTSA/goal-kicker). First call downloads all 100 `*.json` records to `consultant/data/universities/`; subsequent calls read from disk. The cache directory is gitignored. `_trim()` drops the bulky `school_people` block before handing records to the agent, keeping tool results around 8 KB instead of 80 KB.
6. `consultant/db.py` — `students` table holds `profile_json` + `conversation_json` for resume-on-restart. The student's folder path is on the row so renames stay consistent.

## Two things that will bite you

- **Persisted messages must be plain dicts.** `agent.py` calls `.model_dump()` on every `response.content` block before appending. Don't append raw SDK `ContentBlock` objects — they won't survive `json.dumps`, and the next session will fail to reload.
- **System-prompt cache breakpoint.** The long static prompt has `cache_control: ephemeral`. The per-turn `<current_profile>` block comes *after* it so cache hits survive profile updates. If you split or reorder system blocks, keep the breakpoint on the static block — otherwise every turn pays full prefill cost.

## Storage layout

- `consultant.db` — SQLite, one row per student. `profile_json` is schema-free (whatever shape the agent wrote).
- `students/<slug>/` — Markdown artifacts written by `save_artifact`. Slug is alphanumerics from the name, lowercased, with other characters mapped to `_`.
- Both are gitignored.

## Model

`claude-sonnet-4-6`, set as `MODEL` in `consultant/agent.py`. Swap models there; don't add a config layer for a single constant.
