# AI University Consultant

A conversational CLI agent that helps students figure out which universities to apply to. The agent learns each student's situation through natural conversation, saves their case to SQLite, and writes a per-student folder with a profile summary, a 4-university shortlist, per-school application checklists, and a personal-statement draft.

## Setup

```
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then put your ANTHROPIC_API_KEY in .env
```

## Run

```
python main.py
```

Enter your name. New name → new case. Same name → resume where you left off. Type `quit` to save and exit.

## What gets saved

- `consultant.db` — one row per student with the full profile and conversation history.
- `students/<name>/` — Markdown artifacts the agent writes for each case:
  - `01_profile_summary.md`
  - `02_university_shortlist.md` (4 schools with rationale)
  - `03_checklist_<school>.md` (one per shortlisted university)
  - `04_personal_statement_draft.md`

Both `consultant.db` and `students/` are gitignored — they hold per-user data.

## How it works

A standard Anthropic tool-use loop. The agent has four tools:

- `update_profile` — extracts structured facts as it learns them (called silently)
- `save_artifact` — writes a Markdown file to the student's folder
- `list_artifacts` / `read_artifact` — used when resuming an existing case

Model: `claude-sonnet-4-6`. The system prompt is cached with `cache_control: ephemeral` so repeated turns stay cheap.
