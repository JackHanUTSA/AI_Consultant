"""CLI entry point for the AI university consultant."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from consultant.agent import ConsultantAgent
from consultant.db import Database


def main() -> None:
    load_dotenv()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Error: ANTHROPIC_API_KEY not set.")
        print("Copy .env.example to .env and add your Anthropic API key.")
        sys.exit(1)

    root = Path(__file__).parent
    students_root = root / "students"
    students_root.mkdir(exist_ok=True)
    db = Database(root / "consultant.db")

    print("=" * 60)
    print("  AI University Consultant")
    print("=" * 60)

    existing = db.list_students()
    if existing:
        print("\nExisting cases:")
        for s in existing:
            print(f"  - {s['name']}")
    print()

    name = input("Your name: ").strip()
    if not name:
        print("Name required. Goodbye.")
        return

    student = db.get_or_create_student(name, students_root)
    if student["is_new"]:
        print(f"\nNice to meet you, {name}. Let's start building your case.")
    else:
        print(f"\nWelcome back, {name}. Resuming your case.")
    print("(Type 'quit' to save and exit.)\n")

    agent = ConsultantAgent(student, db)
    agent.chat_loop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSaved. Talk soon!")
        sys.exit(0)
