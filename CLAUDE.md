# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Python CLI chat agent that conducts admissions consulting conversations with students, persists each case to SQLite + a per-student folder, and produces Markdown deliverables (profile summary, 4-school shortlist, per-school checklists, personal-statement draft).

## Run

```
python main.py
```

Set `PROVIDER` in `.env` to `anthropic` (default) or `openai`, and provide the matching API key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`). On every run you enter a name and pick a **role** (plain prompt, no auth). For `customer` the student is resolved by name and the same name resumes the case from `consultant.db`.

## Test (`simulate.py`)

```
python simulate.py        # offline role simulation; exits non-zero on any failure
python simulate.py -v
```

`simulate.py` drives the **real** agent loop for each role with a `FakeAnthropicClient` that replays a script of tool calls (no LLM API, no network, throwaway temp DB + temp KB). It asserts the role invariants: tool-catalog filtering, dispatcher gating, profile merge/override persistence, ephemeral staff sessions, `_internal_notes` hidden from the customer agent, `open_case` swapping, and KB admin (`refresh_university`/`remove_university`) on an injected temp `UniversityDB`. Run it after any change to roles, tools, prompts, or persistence. To add a scenario: seed fixtures, build a `ConsultantAgent` for the role, and drive it with `run_agent_turn(agent, user_text, turns)` where each turn is `{"tools": [(name, input), ...]}` or `{"text": "..."}`.

## Roles

Three session roles, chosen at startup. The role drives three things: which **system prompt** is used (`prompts.system_prompt_for`), which **tools** the model can see and call (`tools.tools_for_role`, re-checked in `dispatch_tool`), and whether the **conversation persists**.

- **customer** (default) — talks to the warm consulting agent about *their own* case. Tools: `update_profile`, `save_artifact`, `list/read_artifact`, university KB reads. Conversation persists to the case row, as before.
- **supervisor** — analytical staff agent that can open and manage *any* case: `list_cases`, `open_case`, plus `delete_profile_keys`, `add_internal_note`, `delete_artifact` on top of the customer toolset.
- **admin** — everything supervisor has **plus** knowledge-base administration: `refresh_university` (add/update a record from goal-kicker) and `remove_university`.

Two invariants worth protecting:

- **Staff sessions are ephemeral.** `ConsultantAgent.persist_conversation` is true only for `customer`, so a supervisor/admin chat never overwrites a student's saved `conversation_json`. Their profile/artifact/KB *edits* still persist because the tools write through `db`/disk directly.
- **Internal notes never leak to the customer agent.** Notes are stored on the profile under `_internal_notes`; `_visible_profile()` strips all `_`-prefixed keys before building the `<current_profile>` block for the customer role. Don't surface underscore-prefixed keys to customers, and store any other staff-only field with a leading `_`.

Staff may run with **no case open** (blank at the case prompt). Case-specific tools return "No case is open…" until `open_case` succeeds; the per-turn block then reads `<active_case>` instead of `<student_name>`.

## Architecture

A standard Anthropic tool-use loop. Files in dependency order:

1. `main.py` — boots SQLite, prompts for name + role, then either loads-or-creates the customer's row or (for staff) runs `_staff_select_case` to pick an initial case, and hands off to `ConsultantAgent` with the role.
2. `consultant/agent.py` — owns the message list. `_run_turn()` may iterate multiple times when the model wants tools; it exits the inner loop only when `stop_reason != "tool_use"`. It persists conversation + profile after a turn **only when `persist_conversation`** (customer) and a case is open. Role selects the system prompt, the tool catalog (`self.tools`), and `_visible_profile()` filtering.
3. `consultant/tools.py` — defines the tools and the dispatcher. Each tool carries a `roles` tuple; `tools_for_role(role)` filters the catalog for the model and `dispatch_tool(..., role)` re-checks on every call. Customer tools: `update_profile`, `save_artifact`, `list_artifacts`, `read_artifact`, KB reads. Staff add `list_cases`, `open_case`, `delete_profile_keys`, `add_internal_note`, `delete_artifact`; admin adds `refresh_university`, `remove_university`. `update_profile` does a shallow per-key merge so nested objects (`academics`, `test_scores`, …) accumulate rather than overwrite. `_CASE_TOOLS` is the set that requires an open case.
4. `consultant/prompts.py` — the source of truth for agent behavior, one prompt per role (`SYSTEM_PROMPT` for customer, `SUPERVISOR_PROMPT`, `ADMIN_PROMPT`), selected by `system_prompt_for`. **This is the file to edit when an agent asks weak questions, jumps to recommendations too early, or a staff role needs different guidance.**
5. `consultant/universities.py` — local cache + index over the goal-kicker top-100 US universities knowledge base (https://github.com/JackHanUTSA/goal-kicker). First call downloads all 100 `*.json` records to `consultant/data/universities/`; subsequent calls read from disk. The cache directory is gitignored. `_trim()` drops the bulky `school_people` block before handing records to the agent, keeping tool results around 8 KB instead of 80 KB.
6. `consultant/db.py` — `students` table holds `profile_json` + `conversation_json` for resume-on-restart. The student's folder path is on the row so renames stay consistent. `get_student` is a no-create lookup (used by `open_case` and staff case selection); `list_students` now also reports `profile_keys` per case.

## Two things that will bite you

- **Persisted messages must be plain dicts.** `agent.py` calls `.model_dump()` on every `response.content` block before appending. Don't append raw SDK `ContentBlock` objects — they won't survive `json.dumps`, and the next session will fail to reload.
- **System-prompt cache breakpoint.** The long static prompt has `cache_control: ephemeral`. The per-turn `<current_profile>` block comes *after* it so cache hits survive profile updates. If you split or reorder system blocks, keep the breakpoint on the static block — otherwise every turn pays full prefill cost.

## Storage layout

- `consultant.db` — SQLite, one row per student. `profile_json` is schema-free (whatever shape the agent wrote).
- `students/<slug>/` — Markdown artifacts written by `save_artifact`. Slug is alphanumerics from the name, lowercased, with other characters mapped to `_`.
- Both are gitignored.

## Model

Per-provider constants live in `consultant/agent.py`: `ANTHROPIC_MODEL` (`claude-sonnet-4-6`) and `OPENAI_MODEL` (`gpt-4o`). Swap models there; don't add a config layer for two constants. The OpenAI path goes through `_run_turn_openai`, which converts messages in/out of OpenAI's chat-completions tool-calling format — persistent storage stays in Anthropic-shaped content blocks so a case is the same shape regardless of which backend produced it.
