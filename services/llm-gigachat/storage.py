"""
SQLite-хранилище: протоколы, параметры, отчёты, кэш, версии, audit.
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
        file_hash TEXT,
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
        protocol_id INTEGER,
        file_hash TEXT,
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

    CREATE TABLE IF NOT EXISTS explanation_cache (
        cache_key TEXT PRIMARY KEY,
        rule_id TEXT NOT NULL,
        actual_value TEXT NOT NULL,
        explanation_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        hits INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS rules_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version_label TEXT NOT NULL,
        rules_path TEXT NOT NULL,
        rules_count INTEGER NOT NULL,
        loaded_at TEXT NOT NULL,
        is_active INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        actor TEXT NOT NULL DEFAULT 'admin',
        action TEXT NOT NULL,
        target_type TEXT,
        target_id TEXT,
        details TEXT
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'operator',
        created_at TEXT NOT NULL,
        is_active INTEGER DEFAULT 1
    );

    CREATE INDEX IF NOT EXISTS idx_protocols_hash ON protocols(file_hash);
    CREATE INDEX IF NOT EXISTS idx_protocols_status ON protocols(overall_status);
    CREATE INDEX IF NOT EXISTS idx_reports_hash ON reports(file_hash);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_if_needed(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='protocols'")
    if not cur.fetchone():
        return

    cur = conn.execute("PRAGMA table_info(protocols)")
    cols = {row[1] for row in cur.fetchall()}
    if "file_hash" not in cols and "total_rows" in cols:
        try:
            conn.execute("ALTER TABLE protocols ADD COLUMN file_hash TEXT")
            conn.commit()
            logger.info("Миграция: добавлена колонка file_hash в protocols")
        except sqlite3.OperationalError:
            pass


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
    file_hash: Optional[str] = None,
) -> int:
    total_rows = len(rows_results)
    failed_rows = sum(1 for r in rows_results if r["overall_status"] == "defect")
    warning_rows = sum(1 for r in rows_results if r["overall_status"] == "warning")

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO protocols
               (filename, file_hash, uploaded_at, overall_status, total_rows, failed_rows, warning_rows)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (filename, file_hash, datetime.utcnow().isoformat(),
             overall, total_rows, failed_rows, warning_rows),
        )
        protocol_id = cur.lastrowid

        for row in rows_results:
            for p in row["parameters"]:
                cur.execute(
                    """INSERT INTO parameter_results
                       (protocol_id, row_index, parameter, source_column, actual, norm, unit, status, rule_id, clause)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        protocol_id, row["row_index"], p.get("parameter"),
                        p.get("source_column"), str(p.get("actual")), p.get("norm"),
                        p.get("unit"), p.get("status"), p.get("rule_id"), p.get("clause"),
                    ),
                )

        if report_text:
            cur.execute(
                """INSERT INTO reports (protocol_id, file_hash, report_text, generated_at)
                   VALUES (?, ?, ?, ?)""",
                (protocol_id, file_hash, report_text, datetime.utcnow().isoformat()),
            )

        conn.commit()

    logger.info("Сохранён протокол id=%d, hash=%s, строк=%d",
                protocol_id, (file_hash or "")[:12], total_rows)
    return protocol_id


def get_report_by_hash(file_hash: str) -> Optional[str]:
    if not file_hash:
        return None
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT report_text FROM reports WHERE file_hash = ? ORDER BY id DESC LIMIT 1", (file_hash,))
        row = cur.fetchone()
        return row["report_text"] if row else None


def get_protocol_by_hash(file_hash: str) -> Optional[Dict[str, Any]]:
    if not file_hash:
        return None
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM protocols WHERE file_hash = ? ORDER BY id DESC LIMIT 1", (file_hash,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_recent_protocols(limit: int = 20) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, filename, file_hash, uploaded_at, overall_status, total_rows, failed_rows, warning_rows FROM protocols ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_protocol_details(protocol_id: int) -> Dict[str, Any]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM protocols WHERE id = ?", (protocol_id,))
        protocol = cur.fetchone()
        if not protocol:
            return {}

        cur.execute("SELECT * FROM parameter_results WHERE protocol_id = ? ORDER BY row_index, id", (protocol_id,))
        all_params = [dict(row) for row in cur.fetchall()]

        rows_map: Dict[int, List[Dict[str, Any]]] = {}
        for p in all_params:
            ri = p.get("row_index") or 0
            rows_map.setdefault(ri, []).append(p)

        rows = [{"row_index": ri, "parameters": plist} for ri, plist in sorted(rows_map.items())]

        cur.execute("SELECT report_text FROM reports WHERE protocol_id = ? ORDER BY id DESC LIMIT 1", (protocol_id,))
        report_row = cur.fetchone()

        return {
            "protocol": dict(protocol),
            "rows": rows,
            "report_text": report_row["report_text"] if report_row else None,
        }


def find_similar_protocols(
    current_param_names: List[str],
    exclude_protocol_id: Optional[int] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    if not current_param_names:
        return []

    current_set = set(p.lower().strip() for p in current_param_names if p)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT p.id, p.filename, p.uploaded_at, p.overall_status,
                   p.total_rows, p.failed_rows, p.warning_rows
            FROM protocols p
            JOIN parameter_results pr ON pr.protocol_id = p.id
            WHERE p.id != ?
            ORDER BY p.id DESC
            LIMIT 50
        """, (exclude_protocol_id or -1,))
        candidates = cur.fetchall()

        results = []
        for c in candidates:
            cur.execute(
                "SELECT DISTINCT parameter FROM parameter_results WHERE protocol_id = ? AND parameter IS NOT NULL",
                (c["id"],),
            )
            params = set((row["parameter"] or "").lower().strip() for row in cur.fetchall())
            if not params:
                continue

            intersection = current_set & params
            union = current_set | params
            similarity = len(intersection) / len(union) if union else 0

            if similarity >= 0.5:
                results.append({
                    "protocol_id": c["id"],
                    "filename": c["filename"],
                    "uploaded_at": c["uploaded_at"],
                    "overall_status": c["overall_status"],
                    "total_rows": c["total_rows"],
                    "failed_rows": c["failed_rows"],
                    "warning_rows": c["warning_rows"],
                    "similarity": round(similarity * 100, 1),
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]


# ---------- Кэш маппинга ----------

def _columns_key(columns: List[str]) -> str:
    return "|".join(sorted(c.strip().lower() for c in columns))


def get_cached_mapping(columns: List[str]) -> Optional[Dict[str, str]]:
    key = _columns_key(columns)
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT mapping_json FROM mapping_cache WHERE columns_key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        conn.execute("UPDATE mapping_cache SET hits = hits + 1 WHERE columns_key = ?", (key,))
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


# ---------- Кэш RAG-объяснений ----------

def get_cached_explanation(rule_id: str, actual: Any) -> Optional[Dict[str, Any]]:
    key = f"{rule_id}|{round(float(actual), 2) if isinstance(actual, (int, float)) else actual}"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT explanation_json FROM explanation_cache WHERE cache_key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        conn.execute("UPDATE explanation_cache SET hits = hits + 1 WHERE cache_key = ?", (key,))
        conn.commit()
    return json.loads(row["explanation_json"])


def save_explanation_cache(rule_id: str, actual: Any, explanation: Dict[str, Any]) -> None:
    key = f"{rule_id}|{round(float(actual), 2) if isinstance(actual, (int, float)) else actual}"
    with get_connection() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO explanation_cache
               (cache_key, rule_id, actual_value, explanation_json, created_at, hits)
               VALUES (?, ?, ?, ?, ?, COALESCE((SELECT hits FROM explanation_cache WHERE cache_key = ?), 0))""",
            (key, rule_id, str(actual), json.dumps(explanation, ensure_ascii=False),
             datetime.utcnow().isoformat(), key),
        )
        conn.commit()
    logger.info("RAG-объяснение закэшировано: %s", key)


# ---------- Статистика ----------

def get_stats() -> Dict[str, Any]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM protocols")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM protocols WHERE overall_status = 'good'")
        good = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM protocols WHERE overall_status = 'warning'")
        warning = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM protocols WHERE overall_status = 'defect'")
        defect = cur.fetchone()[0]

        cur.execute("""
            SELECT parameter, COUNT(*) as fails
            FROM parameter_results WHERE status = 'fail'
            GROUP BY parameter ORDER BY fails DESC LIMIT 5
        """)
        top_fails = [{"parameter": r[0], "count": r[1]} for r in cur.fetchall()]

        cur.execute("""
            SELECT DATE(uploaded_at) as day, COUNT(*) as cnt
            FROM protocols GROUP BY day ORDER BY day DESC LIMIT 7
        """)
        by_day = [{"date": r[0], "count": r[1]} for r in cur.fetchall()]
        by_day.reverse()

    return {
        "total": total, "good": good, "warning": warning, "defect": defect,
        "top_fails": top_fails, "by_day": by_day,
    }


def get_protocols_filtered(status: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        if status in ("good", "warning", "defect"):
            cur.execute("SELECT * FROM protocols WHERE overall_status = ? ORDER BY id DESC LIMIT ?", (status, limit))
        else:
            cur.execute("SELECT * FROM protocols ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]


# ---------- Версии нормативов ----------

def register_rules_version(rules_path: str, rules_count: int, version_label: str = "") -> int:
    if not version_label:
        version_label = f"v{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    with get_connection() as conn:
        conn.execute("UPDATE rules_versions SET is_active = 0")
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO rules_versions (version_label, rules_path, rules_count, loaded_at, is_active)
               VALUES (?, ?, ?, ?, 1)""",
            (version_label, rules_path, rules_count, datetime.utcnow().isoformat()),
        )
        version_id = cur.lastrowid
        conn.commit()
    logger.info("Зарегистрирована версия нормативов: %s (id=%d)", version_label, version_id)
    return version_id


def get_active_rules_version() -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM rules_versions WHERE is_active = 1 ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        return dict(row) if row else None


def get_all_rules_versions() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM rules_versions ORDER BY id DESC")
        return [dict(row) for row in cur.fetchall()]


# ---------- Audit log ----------

def log_action(action: str, target_type: str = "", target_id: str = "",
               details: str = "", actor: str = "admin") -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO audit_log (created_at, actor, action, target_type, target_id, details)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (datetime.utcnow().isoformat(), actor, action, target_type, target_id, details),
        )
        conn.commit()


def get_audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in cur.fetchall()]


def export_history_rows() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id as protocol_id, p.filename, p.uploaded_at, p.overall_status,
                   pr.row_index, pr.parameter, pr.actual, pr.norm, pr.unit, pr.status,
                   pr.rule_id, pr.clause
            FROM protocols p
            LEFT JOIN parameter_results pr ON pr.protocol_id = p.id
            ORDER BY p.id DESC, pr.row_index, pr.id
        """)
        return [dict(row) for row in cur.fetchall()]


def get_users() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, role, created_at, is_active FROM users ORDER BY id")
        return [dict(row) for row in cur.fetchall()]