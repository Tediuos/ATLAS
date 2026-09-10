"""Persistent write receipts. An uncertain remote write is never replayed automatically."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path


class WriteJournal:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS writes "
                "(key TEXT PRIMARY KEY, status TEXT NOT NULL, result TEXT)"
            )

    def claim(self, key):
        with closing(sqlite3.connect(self.path, timeout=30)) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status, result FROM writes WHERE key=?", (key,)).fetchone()
            if row:
                if row[0] == "completed":
                    return json.loads(row[1])
                raise RuntimeError(
                    "Previous external write has an uncertain outcome; reconcile it manually"
                )
            conn.execute("INSERT INTO writes (key, status) VALUES (?, 'pending')", (key,))
        return None

    def complete(self, key, result):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                "UPDATE writes SET status='completed', result=? WHERE key=?",
                (json.dumps(result), key),
            )
