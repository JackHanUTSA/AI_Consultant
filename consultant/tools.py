"""Tool definitions and dispatcher for the consultant agent."""
from __future__ import annotations

import json
from pathlib import Path

from consultant.universities import UniversityDB


_UNIVERSITY_DB: UniversityDB | None = None


def _universities() -> UniversityDB:
    global _UNIVERSITY_DB
    if _UNIVERSITY_DB is None:
        cache = Path(__file__).resolve().parent / "data" / "universities"
        _UNIVERSITY_DB = UniversityDB(cache)
    return _UNIVERSITY_DB


TOOLS = [
    {
        "name": "update_profile",
        "description": (
            "Update the student's profile with information learned during conversation. "
            "Pass any subset of fields — only the ones you provide will be merged. "
            "Call this silently every time you learn a concrete fact; do not announce it. "
            "Suggested top-level keys: academics, test_scores, intended_major, career_goals, "
            "geographic_preferences, budget, financial_aid_needed, extracurriculars, awards, "
            "work_experience, recommenders, languages, citizenship, visa_status, family_context, "
            "personality_strengths, hooks, notes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "updates": {
                    "type": "object",
                    "description": (
                        "Object of fields to merge into the profile. Top-level keys with "
                        "object values are merged with the existing object; other values "
                        "replace what's there."
                    ),
                }
            },
            "required": ["updates"],
        },
    },
    {
        "name": "save_artifact",
        "description": (
            "Save a Markdown document into the student's case folder. Use this to write the "
            "profile summary, university shortlist, per-university checklists, and the "
            "personal-statement draft once the profile is rich enough."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "File name with .md extension. No slashes or '..'.",
                },
                "content": {
                    "type": "string",
                    "description": "Full Markdown content of the artifact.",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "list_artifacts",
        "description": "List files already saved in this student's folder.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_artifact",
        "description": "Read an existing artifact from this student's folder.",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
    {
        "name": "list_universities",
        "description": (
            "List every university in the knowledge base (top-100 US schools sourced "
            "from goal-kicker). Returns slug, name, short_name, rank, and majors_count "
            "for each. Use for orientation; narrow with search_universities before "
            "calling get_university."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_universities",
        "description": (
            "Filter the university knowledge base. Pass any combination of: "
            "`major` (case-insensitive substring match against the school's degree "
            "titles), `max_rank` (only schools ranked <= this number), `name_contains` "
            "(case-insensitive substring match against the school name). Returns the "
            "same summary fields as list_universities. Use this to narrow before "
            "calling get_university for shortlist candidates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "major": {"type": "string"},
                "max_rank": {"type": "integer"},
                "name_contains": {"type": "string"},
            },
        },
    },
    {
        "name": "get_university",
        "description": (
            "Fetch the full record for one university by slug (e.g. 'mit', 'uc-berkeley'). "
            "Returns admissions policy, testing/GPA policy, course-rigor expectations, "
            "competitive signals (what successful applicants tend to have), majors list, "
            "and source URLs the student can verify. Call this for every school you put "
            "on the shortlist — do not invent admissions data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
]


def _merge(base: dict, updates: dict) -> dict:
    """Shallow merge per top-level key. Nested dicts are merged one level deep."""
    out = dict(base)
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out[k])
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def dispatch_tool(name: str, args: dict, student: dict, db) -> str:
    folder = Path(student["folder"])

    if name == "update_profile":
        updates = args.get("updates") or {}
        student["profile"] = _merge(student["profile"], updates)
        db.save_profile(student["id"], student["profile"])
        return f"Profile updated. Current keys: {sorted(student['profile'].keys())}"

    if name == "save_artifact":
        filename = args["filename"]
        if "/" in filename or "\\" in filename or ".." in filename:
            return "Error: filename must not contain slashes or '..'"
        if not filename.endswith(".md"):
            filename = filename + ".md"
        path = folder / filename
        path.write_text(args["content"], encoding="utf-8")
        return f"Saved {path.name} ({len(args['content'])} chars)"

    if name == "list_artifacts":
        files = sorted(p.name for p in folder.iterdir() if p.is_file())
        return json.dumps(files) if files else "(empty)"

    if name == "read_artifact":
        path = folder / args["filename"]
        if not path.exists():
            return f"Not found: {args['filename']}"
        return path.read_text(encoding="utf-8")

    if name == "list_universities":
        return json.dumps(_universities().list_all(), indent=2)

    if name == "search_universities":
        results = _universities().search(
            major=args.get("major"),
            max_rank=args.get("max_rank"),
            name_contains=args.get("name_contains"),
        )
        if not results:
            return "No matches."
        return json.dumps(results, indent=2)

    if name == "get_university":
        rec = _universities().get(args["slug"])
        if rec is None:
            return f"No university with slug {args['slug']!r}. Use list_universities to see valid slugs."
        return json.dumps(rec, indent=2)

    return f"Unknown tool: {name}"
