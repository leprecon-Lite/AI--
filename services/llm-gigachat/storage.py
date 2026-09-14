"""
SQLite-хранилище: протоколы, параметры, отчёты, кэш маппинга.
Поддерживает многорядные протоколы (несколько партий в одном файле).
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import settings
from logger import logger


DB_PATH = Path(__file__).parent / settings.db_path


SCHEMA = """
    CREATE TABLE IF NOT EXISTS protocols (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        uploaded_at TEXT NOT NULL,
        overall_status TEXT NOT NULL,
        total_rows INTEGER NOT NULL,
        failed_rows INTEGER NOT NULL,
        warning_rows INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS parameter_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        protocol_id INTEGER NOT NULL,
        row_index INTEGER,
        parameter TEXT,
        source_column TEXT,
        actual TEXT,
        norm TEXT,
        unit TEXT,
        status TEXT,
        rule_id TEXT,
        clause TEXT,
        FOREIGN KEY (protocol_id) REFERENCES protocols(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        protocol_id INTEGER NOT NULL,
        report_text TEXT,
        generated_at TEXT NOT NULL,
        FOREIGN KEY (protocol_id) REFERENCES protocols(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS mapping_cache (
        columns_key TEXT PRIMARY KEY,
        mapping_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        hits INTEGER DEFAULT 0
    );
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_if_needed(conn: sqlite3.Connection) -> None:
    """Если обнаружена старая схема — дропаем несовместимые таблицы."""
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='protocols'"
    )
    if not cur.fetchone():
        return  # таблиц нет, создадутся ниже

    cur = conn.execute("PRAGMA table_info(protocols)")
    cols = {row[1] for row in cur.fetchall()}
    if "total_rows" not in cols:
        logger.warning("Обнаружена старая схема БД, дропаем protocols/reports/parameter_results")
        conn.executescript("""
            DROP TABLE IF EXISTS parameter_results;
            DROP TABLE IF EXISTS reports;
            DROP TABLE IF EXISTS protocols;
        """)
        conn.commit()


def init_db() -> None:
    with get_connection() as conn:
        _migrate_if_needed(conn)
        conn.executescript(SCHEMA)
    logger.info("SQLite инициализирован: %s", DB_PATH)


# ---------- Протоколы ----------

def save_protocol(
    filename: str,
    overall: str,
    rows_results: List[Dict[str, Any]],
    report_text: Optional[str] = None,
) -> int:
    """
    rows_results: [{"row_index": 1, "overall_status": "defect", "parameters": [...]}, ...]
    """
    total_rows = len(rows_results)
    failed_rows = sum(1 for r in rows_results if r["overall_status"] == "defect")
    warning_rows = sum(1 for r in rows_results if r["overall_status"] == "warning")

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO protocols
               (filename, uploaded_at, overall_status, total_rows, failed_rows, warning_rows)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (filename, datetime.utcnow().isoformat(), overall, total_rows, failed_rows, warning_rows),
        )
        protocol_id = cur.lastrowid

        for row in rows_results:
            for p in row["parameters"]:
                cur.execute(
                    """INSERT INTO parameter_results
                       (protocol_id, row_index, parameter, source_column, actual, norm, unit, status, rule_id, clause)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        protocol_id,
                        row["row_index"],
                        p.get("parameter"),
                        p.get("source_column"),
                        str(p.get("actual")),
                        p.get("norm"),
                        p.get("unit"),
                        p.get("status"),
                        p.get("rule_id"),
                        p.get("clause"),
                    ),
                )

        if report_text:
            cur.execute(
                """INSERT INTO reports (protocol_id, report_text, generated_at)
                   VALUES (?, ?, ?)""",
                (protocol_id, report_text, datetime.utcnow().isoformat()),
            )

        conn.commit()
    logger.info(
        "Сохранён протокол id=%d, строк=%d, defect=%d, warning=%d",
        protocol_id, total_rows, failed_rows, warning_rows,
    )
    return protocol_id


def get_recent_protocols(limit: int = 20) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM protocols ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]


def get_protocol_details(protocol_id: int) -> Dict[str, Any]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM protocols WHERE id = ?", (protocol_id,))
        protocol = cur.fetchone()
        if not protocol:
            return {}

        cur.execute(
            "SELECT * FROM parameter_results WHERE protocol_id = ? ORDER BY row_index, id",
            (protocol_id,),
        )
        all_params = [dict(row) for row in cur.fetchall()]

        # Группируем параметры по строкам
        rows_map: Dict[int, List[Dict[str, Any]]] = {}
        for p in all_params:
            ri = p.get("row_index") or 0
            rows_map.setdefault(ri, []).append(p)

        rows = [
            {"row_index": ri, "parameters": plist}
            for ri, plist in sorted(rows_map.items())
        ]

        cur.execute(
            "SELECT report_text FROM reports WHERE protocol_id = ? ORDER BY id DESC LIMIT 1",
            (protocol_id,),
        )
        report_row = cur.fetchone()

        return {
            "protocol": dict(protocol),
            "rows": rows,
            "report_text": report_row["report_text"] if report_row else None,
        }


# ---------- Кэш семантического маппинга ----------

def _columns_key(columns: List[str]) -> str:
    return "|".join(sorted(c.strip().lower() for c in columns))


def get_cached_mapping(columns: List[str]) -> Optional[Dict[str, str]]:
    key = _columns_key(columns)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT mapping_json FROM mapping_cache WHERE columns_key = ?",
            (key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE mapping_cache SET hits = hits + 1 WHERE columns_key = ?",
            (key,),
        )
        conn.commit()
    return json.loads(row["mapping_json"])


def save_mapping_cache(columns: List[str], mapping: Dict[str, str]) -> None:
    key = _columns_key(columns)
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO mapping_cache (columns_key, mapping_json, created_at, hits)
               VALUES (?, ?, ?, COALESCE((SELECT hits FROM mapping_cache WHERE columns_key = ?), 0))""",
            (key, json.dumps(mapping, ensure_ascii=False), datetime.utcnow().isoformat(), key),
        )
        conn.commit()
    logger.info("Кэш маппинга сохранён для колонок: %s", key[:80])