from pathlib import Path
import sqlite3

import pandas as pd


database_path = Path("podman_check.db")

with sqlite3.connect(database_path) as connection:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS environment_check (
            id INTEGER PRIMARY KEY,
            message TEXT NOT NULL
        )
        """
    )
    connection.execute(
        "INSERT INTO environment_check (message) VALUES (?)",
        ("Python and SQLite work inside Podman.",),
    )
    connection.commit()

    row_count = connection.execute(
        "SELECT COUNT(*) FROM environment_check"
    ).fetchone()[0]

print(f"pandas version: {pd.__version__}")
print(f"SQLite version: {sqlite3.sqlite_version}")
print(f"Database: {database_path.resolve()}")
print(f"Saved rows: {row_count}")
