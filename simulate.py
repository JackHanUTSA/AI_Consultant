"""Offline role-simulation harness for the AI University Consultant.

Runs each role (customer / supervisor / admin) through realistic scenarios and
asserts the system behaves correctly — WITHOUT calling any LLM API or touching
your real database or university cache.

How it works:
  * A FakeAnthropicClient replaces the real SDK client. It emits a scripted
    sequence of tool calls (and a closing text reply) so the real agent loop in
    `consultant/agent.py` runs end to end against deterministic "model" output.
  * Everything runs in a temp dir: a throwaway SQLite DB, a throwaway student
    folder, and a throwaway university knowledge base seeded in-memory (no
    network, no edits to consultant/data/universities).

Run:
    python simulate.py            # full report, exits non-zero on any failure
    python simulate.py -v         # also print the agent's scripted replies
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# The agent constructs a real Anthropic() client in __init__, which only needs a
# key present (no network at construction). We immediately swap in the fake.
os.environ.setdefault("ANTHROPIC_API_KEY", "sim-not-used")
os.environ.pop("PROVIDER", None)  # force the anthropic path

import consultant.tools as tools_mod
import consultant.universities as uni_mod
from consultant.agent import ConsultantAgent
from consultant.db import Database
from consultant.tools import dispatch_tool, tools_for_role
from consultant.universities import UniversityDB

VERBOSE = "-v" in sys.argv


# --------------------------------------------------------------------------- #
# Fake LLM client: emits scripted tool calls / text, matching the SDK shape
# the agent consumes (block.type / .text / .name / .input / .id / .model_dump).
# --------------------------------------------------------------------------- #
class _Block:
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def model_dump(self) -> dict:
        if self.type == "text":
            return {"type": "text", "text": self.text}
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


class _Response:
    def __init__(self, content: list, stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


class _Messages:
    def __init__(self, client: "FakeAnthropicClient"):
        self._client = client

    def create(self, **kwargs) -> _Response:
        return self._client._next(kwargs)


class FakeAnthropicClient:
    """Replays a script of turns. Each turn is either:
        {"tools": [(name, input_dict), ...]}   -> stop_reason="tool_use"
        {"text": "..."}                          -> stop_reason="end_turn"
    """

    def __init__(self, turns: list[dict]):
        self._turns = list(turns)
        self._uid = 0
        self.tool_payloads_seen: list[list] = []  # the `tools` arg each call got
        self.messages = _Messages(self)

    def _next(self, kwargs: dict) -> _Response:
        # Record which tools the agent advertised this call (role-filtered set).
        self.tool_payloads_seen.append([t["name"] for t in kwargs.get("tools", [])])
        if not self._turns:
            raise AssertionError("FakeAnthropicClient ran out of scripted turns")
        spec = self._turns.pop(0)
        if "text" in spec:
            return _Response([_Block(type="text", text=spec["text"])], "end_turn")
        blocks = []
        for name, payload in spec["tools"]:
            self._uid += 1
            blocks.append(
                _Block(type="tool_use", id=f"tu_{self._uid}", name=name, input=payload)
            )
        return _Response(blocks, "tool_use")


# --------------------------------------------------------------------------- #
# Report helper
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.failures: list[str] = []

    def check(self, desc: str, ok: bool, detail: str = "") -> None:
        if ok:
            self.passed += 1
            print(f"    \033[32mPASS\033[0m  {desc}")
        else:
            self.failed += 1
            self.failures.append(desc)
            suffix = f"  ({detail})" if detail else ""
            print(f"    \033[31mFAIL\033[0m  {desc}{suffix}")

    def section(self, title: str) -> None:
        print(f"\n\033[1m{title}\033[0m")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
def no_case() -> dict:
    return {"id": None, "name": None, "folder": None,
            "profile": {}, "conversation": [], "is_new": False}


def make_uni(slug: str, name: str, rank: int, majors: list[str]) -> dict:
    return {
        "slug": slug, "name": name, "short_name": name, "rank": rank,
        "official_domain": f"{slug}.edu",
        "source_urls": {"admissions": [f"https://{slug}.edu/apply"]},
        "majors": {"count": len(majors), "titles": majors},
        "admissions": {}, "competitive_signals": {},
        "verification": {"last_verified_at": "2026-01-01",
                         "confidence": "high", "unknown_fields": []},
    }


def seed_kb(cache_dir: Path) -> UniversityDB:
    """A temp knowledge base with two records, pre-loaded so no network sync runs."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    recs = {
        "mit": make_uni("mit", "MIT", 1, ["Computer Science", "Aerospace"]),
        "stanford": make_uni("stanford", "Stanford University", 3, ["Computer Science"]),
    }
    for slug, rec in recs.items():
        (cache_dir / f"{slug}.json").write_text(json.dumps(rec), "utf-8")
    udb = UniversityDB(cache_dir)
    udb._records = dict(recs)  # bypass _ensure_synced (no network)
    return udb


def run_agent_turn(agent: ConsultantAgent, user_text: str, turns: list[dict]):
    """Drive one user turn through the real agent loop with a scripted fake LLM."""
    agent.client = FakeAnthropicClient(turns)
    agent.messages.append({"role": "user", "content": user_text})
    agent._run_turn()
    return agent.client


# --------------------------------------------------------------------------- #
# Scenarios
# --------------------------------------------------------------------------- #
def scenario_customer(db: Database, students_root: Path, r: Report) -> None:
    r.section("CUSTOMER — own case, warm consulting, conversation persists")

    visible = sorted(t["name"] for t in tools_for_role("customer"))
    r.check("tool catalog excludes staff/admin tools",
            not ({"open_case", "list_cases", "delete_artifact", "refresh_university",
                  "remove_university", "add_internal_note", "delete_profile_keys"} & set(visible)),
            str(visible))

    alice = db.get_or_create_student("Alice", students_root)
    agent = ConsultantAgent(alice, db, role="customer", actor_name="Alice")
    r.check("customer conversation is persistent", agent.persist_conversation is True)

    fake = run_agent_turn(
        agent, "Hi, I'm a junior with a 3.9 GPA interested in CS.",
        [
            {"tools": [
                ("update_profile", {"updates": {"academics": {"gpa": 3.9},
                                                "intended_major": "Computer Science"}}),
                ("save_artifact", {"filename": "01_profile_summary.md",
                                   "content": "# Alice\nGPA 3.9, CS."}),
            ]},
            {"text": "Got it — saved a first profile summary for you."},
        ],
    )

    reloaded = db.get_student("Alice")
    r.check("profile merged + persisted",
            reloaded["profile"].get("academics", {}).get("gpa") == 3.9, str(reloaded["profile"]))
    r.check("artifact written to case folder",
            (Path(alice["folder"]) / "01_profile_summary.md").exists())
    r.check("conversation persisted to DB", len(reloaded["conversation"]) > 0,
            f"{len(reloaded['conversation'])} messages")
    r.check("agent was only offered customer tools",
            all("open_case" not in names for names in fake.tool_payloads_seen))

    # Gating: a customer attempting a staff tool is refused by the dispatcher.
    out = dispatch_tool("open_case", {"name": "Alice"}, alice, db, "customer")
    r.check("dispatcher blocks customer from open_case", out.startswith("Error: role"), out)
    out = dispatch_tool("refresh_university", {"slug": "mit"}, alice, db, "customer")
    r.check("dispatcher blocks customer from refresh_university", out.startswith("Error: role"), out)


def scenario_internal_notes_hidden(db: Database, students_root: Path, r: Report) -> None:
    r.section("PRIVACY — staff internal notes never reach the customer agent")

    case = db.get_or_create_student("Carol", students_root)
    case["profile"] = {"intended_major": "Biology",
                       "_internal_notes": [{"at": "2026-01-01", "note": "Reach list too optimistic"}]}

    cust = ConsultantAgent(case, db, role="customer")
    sup = ConsultantAgent(case, db, role="supervisor")

    r.check("customer _visible_profile() omits _internal_notes",
            "_internal_notes" not in cust._visible_profile())
    r.check("customer profile block omits the note text",
            "too optimistic" not in cust._profile_block_text())
    r.check("supervisor _visible_profile() includes _internal_notes",
            "_internal_notes" in sup._visible_profile())
    r.check("customer still sees normal fields",
            "intended_major" in cust._visible_profile())


def scenario_supervisor(db: Database, students_root: Path, r: Report) -> None:
    r.section("SUPERVISOR — open any case, override, notes, ephemeral session")

    # A student case the supervisor will audit, seeded with a wrong field.
    bob = db.get_or_create_student("Bob", students_root)
    bob["profile"] = {"academics": {"gpa": 3.2}, "wrong_field": "stale value"}
    db.save_profile(bob["id"], bob["profile"])

    visible = sorted(t["name"] for t in tools_for_role("supervisor"))
    r.check("supervisor sees case-management tools",
            {"list_cases", "open_case", "delete_profile_keys", "add_internal_note",
             "delete_artifact"} <= set(visible))
    r.check("supervisor does NOT see admin KB tools",
            not ({"refresh_university", "remove_university"} & set(visible)))

    staff = no_case()
    agent = ConsultantAgent(staff, db, role="supervisor", actor_name="Dr. Smith")
    r.check("supervisor conversation is ephemeral", agent.persist_conversation is False)
    r.check("no-case profile block flags it",
            "no case open" in agent._profile_block_text().lower())

    run_agent_turn(
        agent, "Open Bob's case, drop the stale field, and leave a note.",
        [
            {"tools": [("list_cases", {}), ("open_case", {"name": "Bob"})]},
            {"tools": [
                ("delete_profile_keys", {"keys": ["wrong_field"]}),
                ("add_internal_note", {"note": "Borderline for top-10; recommend safety schools."}),
            ]},
            {"text": "Done — removed the stale field and added a supervisor note."},
        ],
    )

    r.check("active case swapped to Bob", staff.get("name") == "Bob")
    bob_db = db.get_student("Bob")
    r.check("override persisted: wrong_field removed", "wrong_field" not in bob_db["profile"])
    notes = bob_db["profile"].get("_internal_notes")
    r.check("internal note persisted on the case",
            isinstance(notes, list) and any("Borderline" in n["note"] for n in notes))
    r.check("supervisor session NOT written to Bob's conversation",
            bob_db["conversation"] == [], f"{len(bob_db['conversation'])} messages")

    # Gating + no-case guards.
    out = dispatch_tool("remove_university", {"slug": "mit"}, staff, db, "supervisor")
    r.check("dispatcher blocks supervisor from remove_university", out.startswith("Error: role"), out)
    fresh = no_case()
    out = dispatch_tool("update_profile", {"updates": {"x": 1}}, fresh, db, "supervisor")
    r.check("case tool refused when no case is open", out.startswith("No case is open"), out)


def scenario_admin(db: Database, students_root: Path, kb_dir: Path, r: Report) -> None:
    r.section("ADMIN — supervisor powers + knowledge-base administration")

    udb = seed_kb(kb_dir)
    tools_mod._UNIVERSITY_DB = udb  # inject temp KB into the dispatcher

    # Monkeypatch the network fetch so refresh_university works offline.
    class _FakeHTTP:
        def __init__(self, data): self._data = data
        def read(self): return self._data
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(url, timeout=0):
        slug = url.rstrip("/").split("/")[-1].removesuffix(".json")
        rec = make_uni(slug, "Duke University", 10, ["Computer Science", "Economics"])
        return _FakeHTTP(json.dumps(rec).encode())

    uni_mod.urllib.request.urlopen = fake_urlopen

    visible = sorted(t["name"] for t in tools_for_role("admin"))
    r.check("admin sees KB-admin tools",
            {"refresh_university", "remove_university"} <= set(visible))
    r.check("admin also has all supervisor tools",
            {"open_case", "add_internal_note", "delete_profile_keys"} <= set(visible))

    staff = no_case()
    agent = ConsultantAgent(staff, db, role="admin", actor_name="root")
    r.check("admin conversation is ephemeral", agent.persist_conversation is False)

    run_agent_turn(
        agent, "Remove MIT and add Duke to the knowledge base.",
        [
            {"tools": [("list_universities", {})]},
            {"tools": [("remove_university", {"slug": "mit"})]},
            {"tools": [("refresh_university", {"slug": "duke"})]},
            {"text": "Knowledge base updated: removed MIT, added Duke."},
        ],
    )

    r.check("remove_university dropped the record", "mit" not in udb._records)
    r.check("refresh_university added the new record", "duke" in udb._records)
    r.check("KB record count is correct (stanford + duke)", len(udb._records) == 2,
            str(sorted(udb._records)))
    r.check("admin KB ops do not touch the real cache dir",
            kb_dir != (Path(uni_mod.__file__).parent / "data" / "universities"))

    # Gating: only admin may run KB admin (re-confirm via a fresh customer call).
    cust = db.get_or_create_student("Dan", students_root)
    out = dispatch_tool("remove_university", {"slug": "stanford"}, cust, db, "customer")
    r.check("dispatcher blocks non-admin from remove_university", out.startswith("Error: role"), out)
    r.check("blocked call left KB untouched", "stanford" in udb._records)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    print("=" * 64)
    print("  AI University Consultant — role simulation (offline, no API)")
    print("=" * 64)

    r = Report()
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        students_root = tmpd / "students"
        students_root.mkdir()
        db = Database(tmpd / "consultant.db")

        scenario_customer(db, students_root, r)
        scenario_internal_notes_hidden(db, students_root, r)
        scenario_supervisor(db, students_root, r)
        scenario_admin(db, students_root, tmpd / "kb", r)

    print("\n" + "=" * 64)
    total = r.passed + r.failed
    if r.failed == 0:
        print(f"  \033[32mALL {total} CHECKS PASSED\033[0m")
    else:
        print(f"  \033[31m{r.failed}/{total} CHECKS FAILED\033[0m")
        for f in r.failures:
            print(f"    - {f}")
    print("=" * 64)
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())
