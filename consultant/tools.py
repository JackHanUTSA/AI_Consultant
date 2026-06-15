"""Tool definitions and dispatcher for the consultant agent.

Tools are gated by session role. Each tool carries a ``roles`` tuple listing
which roles may see and call it; ``tools_for_role`` filters the catalog for the
model and ``dispatch_tool`` re-checks on every call so a model can never invoke
a tool outside its role.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from consultant.universities import UniversityDB


ALL_ROLES = ("customer", "supervisor", "admin")
_STAFF = ("supervisor", "admin")
_ADMIN = ("admin",)


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
        "roles": ALL_ROLES,
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
        "roles": ALL_ROLES,
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
        "roles": ALL_ROLES,
        "description": "List files already saved in this student's folder.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_artifact",
        "roles": ALL_ROLES,
        "description": "Read an existing artifact from this student's folder.",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
    {
        "name": "list_universities",
        "roles": ALL_ROLES,
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
        "roles": ALL_ROLES,
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
        "roles": ALL_ROLES,
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
    # ---- Staff (supervisor + admin) ----
    {
        "name": "list_cases",
        "roles": _STAFF,
        "description": (
            "List every student case in the system (name, last-updated time, and how "
            "many profile fields are filled in). Use to find a case before open_case."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_case",
        "roles": _STAFF,
        "description": (
            "Load a student's case by exact name so subsequent profile/artifact tools "
            "operate on it. This becomes the active case shown in <active_case>."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
    {
        "name": "delete_profile_keys",
        "roles": _STAFF,
        "description": (
            "Remove one or more top-level keys from the active case's profile. Use to "
            "correct the record when a field is wrong or stale. Persists immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keys": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["keys"],
        },
    },
    {
        "name": "add_internal_note",
        "roles": _STAFF,
        "description": (
            "Append a timestamped staff-only note to the active case. Internal notes are "
            "stored on the case but are NEVER shown to the customer-facing agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        },
    },
    {
        "name": "delete_artifact",
        "roles": _STAFF,
        "description": "Delete a Markdown artifact from the active case's folder.",
        "input_schema": {
            "type": "object",
            "properties": {"filename": {"type": "string"}},
            "required": ["filename"],
        },
    },
    # ---- Admin only ----
    {
        "name": "refresh_university",
        "roles": _ADMIN,
        "description": (
            "(Re)download a university record from the goal-kicker source by slug. Adds "
            "it if new, updates it if it already exists. Use to add a school to the "
            "knowledge base or to refresh a stale/low-confidence record."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    {
        "name": "remove_university",
        "roles": _ADMIN,
        "description": "Remove a university record from the knowledge base by slug.",
        "input_schema": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
]


def tools_for_role(role: str) -> list[dict]:
    """Return the API-shaped tool catalog visible to ``role`` (no ``roles`` key)."""
    out: list[dict] = []
    for tool in TOOLS:
        if role in tool.get("roles", ALL_ROLES):
            out.append({k: v for k, v in tool.items() if k != "roles"})
    return out


def _role_can(role: str, name: str) -> bool:
    for tool in TOOLS:
        if tool["name"] == name:
            return role in tool.get("roles", ALL_ROLES)
    return False


# Tools that require an active case to be open.
_CASE_TOOLS = frozenset(
    {
        "update_profile",
        "save_artifact",
        "list_artifacts",
        "read_artifact",
        "delete_profile_keys",
        "add_internal_note",
        "delete_artifact",
    }
)


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


def dispatch_tool(name: str, args: dict, student: dict, db, role: str = "customer") -> str:
    if not _role_can(role, name):
        return f"Error: role {role!r} is not permitted to use {name!r}."

    if name in _CASE_TOOLS and not student.get("id"):
        return "No case is open. Use open_case(name) to select one first."

    if name == "list_cases":
        cases = db.list_students()
        if not cases:
            return "No cases yet."
        return json.dumps(cases, indent=2)

    if name == "open_case":
        target = db.get_student(args["name"])
        if target is None:
            return f"No case named {args['name']!r}. Use list_cases to see valid names."
        student.clear()
        student.update(target)
        return (
            f"Opened case: {target['name']} "
            f"(profile keys: {sorted(student['profile'].keys())})"
        )

    if name == "refresh_university":
        return json.dumps(_universities().refresh(args["slug"]))

    if name == "remove_university":
        return json.dumps(_universities().remove(args["slug"]))

    folder = Path(student["folder"])

    if name == "delete_profile_keys":
        keys = args.get("keys") or []
        removed = [k for k in keys if k in student["profile"]]
        for k in removed:
            del student["profile"][k]
        db.save_profile(student["id"], student["profile"])
        return f"Removed {removed}. Current keys: {sorted(student['profile'].keys())}"

    if name == "add_internal_note":
        notes = student["profile"].get("_internal_notes")
        if not isinstance(notes, list):
            notes = []
        notes.append(
            {"at": datetime.utcnow().isoformat(), "note": args["note"]}
        )
        student["profile"]["_internal_notes"] = notes
        db.save_profile(student["id"], student["profile"])
        return f"Internal note added ({len(notes)} total). Not visible to the customer."

    if name == "delete_artifact":
        filename = args["filename"]
        if "/" in filename or "\\" in filename or ".." in filename:
            return "Error: filename must not contain slashes or '..'"
        path = folder / filename
        if not path.exists():
            return f"Not found: {filename}"
        path.unlink()
        return f"Deleted {filename}"

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
