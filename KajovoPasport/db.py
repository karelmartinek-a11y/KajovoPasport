from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime(ISO_FMT)


@dataclass
class Card:
    id: int
    name: str
    created_at: str
    updated_at: str


class Database:
    def __init__(self, path: str):
        self.path = str(Path(path))
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._ensure_schema()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def _ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cards(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS images(
                card_id INTEGER NOT NULL,
                field_key TEXT NOT NULL,
                png BLOB,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (card_id, field_key),
                FOREIGN KEY(card_id) REFERENCES cards(id) ON DELETE CASCADE
            );
            """
        )
        self.conn.commit()

    def list_cards(self) -> List[Card]:
        rows = self.conn.execute("SELECT id, name, created_at, updated_at FROM cards ORDER BY name COLLATE NOCASE;").fetchall()
        return [Card(int(r["id"]), str(r["name"]), str(r["created_at"]), str(r["updated_at"])) for r in rows]

    def create_card(self, name: str) -> Card:
        ts = now_utc()
        cur = self.conn.execute("INSERT INTO cards(name, created_at, updated_at) VALUES(?,?,?);", (name, ts, ts))
        self.conn.commit()
        card_id = int(cur.lastrowid)
        return Card(card_id, name, ts, ts)

    def rename_card(self, card_id: int, new_name: str) -> None:
        ts = now_utc()
        self.conn.execute("UPDATE cards SET name=?, updated_at=? WHERE id=?;", (new_name, ts, card_id))
        self.conn.commit()

    def delete_card(self, card_id: int) -> None:
        self.conn.execute("DELETE FROM cards WHERE id=?;", (card_id,))
        self.conn.commit()

    def touch_card(self, card_id: int) -> None:
        ts = now_utc()
        self.conn.execute("UPDATE cards SET updated_at=? WHERE id=?;", (ts, card_id))
        self.conn.commit()

    def get_images_for_card(self, card_id: int) -> Dict[str, bytes]:
        rows = self.conn.execute("SELECT field_key, png FROM images WHERE card_id=?;", (card_id,)).fetchall()
        out: Dict[str, bytes] = {}
        for r in rows:
            if r["png"] is not None:
                out[str(r["field_key"])] = bytes(r["png"])
        return out

    def get_image(self, card_id: int, field_key: str) -> Optional[bytes]:
        row = self.conn.execute(
            "SELECT png FROM images WHERE card_id=? AND field_key=?;", (card_id, field_key)
        ).fetchone()
        if not row or row["png"] is None:
            return None
        return bytes(row["png"])

    def set_image(self, card_id: int, field_key: str, png_bytes: Optional[bytes]) -> None:
        ts = now_utc()
        self.conn.execute(
            """
            INSERT INTO images(card_id, field_key, png, updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(card_id, field_key) DO UPDATE SET png=excluded.png, updated_at=excluded.updated_at;
            """,
            (card_id, field_key, png_bytes, ts),
        )
        self.touch_card(card_id)

    def clear_image(self, card_id: int, field_key: str) -> None:
        self.set_image(card_id, field_key, None)

    def commit(self) -> None:
        self.conn.commit()


def copy_db_file(src_path: str, dst_path: str) -> None:
    src = Path(src_path)
    dst = Path(dst_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Make sure WAL/shm are also copied if present (SQLite WAL mode).
    shutil.copy2(src, dst)
    for suffix in ("-wal", "-shm"):
        if Path(str(src) + suffix).exists():
            shutil.copy2(Path(str(src) + suffix), Path(str(dst) + suffix))
