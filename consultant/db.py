"""SQLite persistence for student cases."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class Database:
    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                folder TEXT NOT NULL,
                profile_json TEXT NOT NULL DEFAULT '{}',
                conversation_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def list_students(self) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT name, updated_at FROM students ORDER BY updated_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def get_or_create_student(self, name: str, students_root: Path) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM students WHERE name = ?", (name,)
        ).fetchone()
        if row:
            d = dict(row)
            return {
                "id": d["id"],
                "name": d["name"],
                "folder": d["folder"],
                "profile": json.loads(d["profile_json"]),
                "conversation": json.loads(d["conversation_json"]),
                "is_new": False,
            }

        slug = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
        folder = students_root / slug
        folder.mkdir(exist_ok=True)
        now = datetime.utcnow().isoformat()
        cur = self.conn.execute(
            "INSERT INTO students (name, folder, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (name, str(folder), now, now),
        )
        self.conn.commit()
        return {
            "id": cur.lastrowid,
            "name": name,
            "folder": str(folder),
            "profile": {},
            "conversation": [],
            "is_new": True,
        }

    def save_profile(self, student_id: int, profile: dict) -> None:
        self.conn.execute(
            "UPDATE students SET profile_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(profile, indent=2), datetime.utcnow().isoformat(), student_id),
        )
        self.conn.commit()

    def save_conversation(self, student_id: int, conversation: list) -> None:
        self.conn.execute(
            "UPDATE students SET conversation_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(conversation), datetime.utcnow().isoformat(), student_id),
        )
        self.conn.commit()
