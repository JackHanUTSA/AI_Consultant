"""CLI entry point for the AI university consultant."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from consultant.agent import ConsultantAgent
from consultant.db import Database


def main() -> None:
    load_dotenv()

    provider = (os.environ.get("PROVIDER") or "anthropic").lower()
    if provider == "openai":
        required_key = "OPENAI_API_KEY"
    elif provider == "anthropic":
        required_key = "ANTHROPIC_API_KEY"
    else:
        print(f"Error: PROVIDER={provider!r} is invalid. Use 'anthropic' or 'openai'.")
        sys.exit(1)

    if not os.environ.get(required_key):
        print(f"Error: {required_key} not set (PROVIDER={provider}).")
        print("Copy .env.example to .env and fill in the relevant key.")
        sys.exit(1)

    root = Path(__file__).parent
    students_root = root / "students"
    students_root.mkdir(exist_ok=True)
    db = Database(root / "consultant.db")

    print("=" * 60)
    print("  AI University Consultant")
    print("=" * 60)

    name = input("\nYour name: ").strip()
    if not name:
        print("Name required. Goodbye.")
        return

    role = (input("Role [customer / supervisor / admin] (default customer): ").strip().lower()
            or "customer")
    if role not in ("customer", "supervisor", "admin"):
        print(f"Unknown role {role!r}; defaulting to 'customer'.")
        role = "customer"

    if role == "customer":
        student = db.get_or_create_student(name, students_root)
        if student["is_new"]:
            print(f"\nNice to meet you, {name}. Let's start building your case.")
        else:
            print(f"\nWelcome back, {name}. Resuming your case.")
    else:
        student = _staff_select_case(db, students_root, role, name)

    print("(Type 'quit' to save and exit.)\n")

    agent = ConsultantAgent(student, db, role=role, actor_name=name)
    agent.chat_loop()


def _no_case() -> dict:
    return {
        "id": None,
        "name": None,
        "folder": None,
        "profile": {},
        "conversation": [],
        "is_new": False,
    }


def _staff_select_case(db, students_root, role: str, name: str) -> dict:
    """Let a supervisor/admin pick an initial case to open (or start with none)."""
    cases = db.list_students()
    print(f"\nSigned in as {role}: {name}.")
    if cases:
        print("\nExisting cases:")
        for s in cases:
            print(f"  - {s['name']}  ({s['profile_keys']} profile fields, updated {s['updated_at'][:10]})")
    else:
        print("\nNo cases exist yet.")

    choice = input(
        "\nOpen which case? (exact name, blank for none"
        + (", 'new:<name>' to create" if role else "")
        + "): "
    ).strip()

    if not choice:
        return _no_case()
    if choice.startswith("new:"):
        new_name = choice[4:].strip()
        if not new_name:
            return _no_case()
        return db.get_or_create_student(new_name, students_root)

    student = db.get_student(choice)
    if student is None:
        print(f"No case named {choice!r}; starting with no case open.")
        return _no_case()
    print(f"Opened case: {student['name']}.")
    return student


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSaved. Talk soon!")
        sys.exit(0)
