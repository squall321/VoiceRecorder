# SQLite 저장소 — 프로젝트/씬/보이스/발음사전/작업 4+1 테이블. ORM 없이 stdlib sqlite3 만 쓴다

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    raw_script        TEXT NOT NULL DEFAULT '',
    engine            TEXT NOT NULL,
    language          TEXT NOT NULL,
    voice_id          TEXT,
    speed             REAL NOT NULL DEFAULT 1.0,
    gap_ms            INTEGER NOT NULL DEFAULT 400,
    read_numbers      INTEGER NOT NULL DEFAULT 1,
    exaggeration      REAL NOT NULL DEFAULT 0.5,
    cfg_weight        REAL NOT NULL DEFAULT 0.5,
    temperature       REAL NOT NULL DEFAULT 0.8,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scenes (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    position          INTEGER NOT NULL,
    number            INTEGER,
    title             TEXT,
    text              TEXT NOT NULL,
    target_start_sec  REAL,
    target_end_sec    REAL,
    voice_id          TEXT,
    speed             REAL,
    gap_before_ms     INTEGER,
    gap_after_ms      INTEGER,
    exaggeration      REAL,
    cfg_weight        REAL,
    temperature       REAL,
    synth_hash        TEXT,
    raw_duration_sec  REAL,
    duration_sec      REAL,
    error             TEXT,
    updated_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenes_project ON scenes(project_id, position);

CREATE TABLE IF NOT EXISTS voices (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    filename          TEXT NOT NULL,
    duration_sec      REAL NOT NULL,
    created_at        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS dictionary (
    id                TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    target            TEXT NOT NULL,
    created_at        REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    id                TEXT PRIMARY KEY,
    project_id        TEXT NOT NULL,
    kind              TEXT NOT NULL,
    status            TEXT NOT NULL,
    total             INTEGER NOT NULL DEFAULT 0,
    done              INTEGER NOT NULL DEFAULT 0,
    current           TEXT,
    error             TEXT,
    result            TEXT,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id, created_at DESC);
"""

_write_lock = threading.Lock()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> float:
    return time.time()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def write() -> Iterator[sqlite3.Connection]:
    """쓰기는 직렬화한다 — 워커 스레드와 요청 스레드가 같은 DB 를 건드린다."""
    with _write_lock, connect() as conn:
        yield conn


def init_db() -> None:
    config.ensure_dirs()
    with write() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)


# ── 프로젝트 ────────────────────────────────────────────────────────────────

_PROJECT_FIELDS = (
    "title",
    "raw_script",
    "engine",
    "language",
    "voice_id",
    "speed",
    "gap_ms",
    "read_numbers",
    "exaggeration",
    "cfg_weight",
    "temperature",
)


def create_project(**values: Any) -> str:
    project_id = new_id()
    ts = now()
    row = {
        "id": project_id,
        "title": values.get("title") or "제목 없는 내레이션",
        "raw_script": values.get("raw_script") or "",
        "engine": values.get("engine") or config.DEFAULT_ENGINE,
        "language": values.get("language") or config.DEFAULT_LANGUAGE,
        "voice_id": values.get("voice_id"),
        "speed": values.get("speed", 1.0),
        "gap_ms": values.get("gap_ms", config.DEFAULT_GAP_MS),
        "read_numbers": 1 if values.get("read_numbers", True) else 0,
        "exaggeration": values.get("exaggeration", 0.5),
        "cfg_weight": values.get("cfg_weight", 0.5),
        "temperature": values.get("temperature", 0.8),
        "created_at": ts,
        "updated_at": ts,
    }
    columns = ", ".join(row)
    placeholders = ", ".join(f":{k}" for k in row)
    with write() as conn:
        conn.execute(f"INSERT INTO projects ({columns}) VALUES ({placeholders})", row)
    return project_id


def get_project(project_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return dict(row) if row else None


def list_projects() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.*, (SELECT COUNT(*) FROM scenes s WHERE s.project_id = p.id) AS scene_count
            FROM projects p ORDER BY p.updated_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def update_project(project_id: str, patch: dict[str, Any]) -> None:
    fields = {k: v for k, v in patch.items() if k in _PROJECT_FIELDS and v is not None}
    if "read_numbers" in fields:
        fields["read_numbers"] = 1 if fields["read_numbers"] else 0
    if not fields:
        return
    fields["updated_at"] = now()
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    with write() as conn:
        conn.execute(
            f"UPDATE projects SET {assignments} WHERE id = :id",
            {**fields, "id": project_id},
        )


def touch_project(project_id: str) -> None:
    with write() as conn:
        conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now(), project_id))


def delete_project(project_id: str) -> None:
    with write() as conn:
        conn.execute("DELETE FROM scenes WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM jobs WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ── 씬 ──────────────────────────────────────────────────────────────────────

_SCENE_FIELDS = (
    "number",
    "title",
    "text",
    "target_start_sec",
    "target_end_sec",
    "voice_id",
    "speed",
    "gap_before_ms",
    "gap_after_ms",
    "exaggeration",
    "cfg_weight",
    "temperature",
)


def insert_scene(project_id: str, position: int, **values: Any) -> str:
    scene_id = new_id()
    row: dict[str, Any] = {
        "id": scene_id,
        "project_id": project_id,
        "position": position,
        "updated_at": now(),
    }
    for field in _SCENE_FIELDS:
        row[field] = values.get(field)
    row["text"] = values.get("text") or ""
    columns = ", ".join(row)
    placeholders = ", ".join(f":{k}" for k in row)
    with write() as conn:
        conn.execute(f"INSERT INTO scenes ({columns}) VALUES ({placeholders})", row)
    return scene_id


def list_scenes(project_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM scenes WHERE project_id = ? ORDER BY position", (project_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_scene(scene_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM scenes WHERE id = ?", (scene_id,)).fetchone()
    return dict(row) if row else None


def update_scene(scene_id: str, patch: dict[str, Any]) -> None:
    fields = {k: v for k, v in patch.items() if k in _SCENE_FIELDS}
    if not fields:
        return
    fields["updated_at"] = now()
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    with write() as conn:
        conn.execute(
            f"UPDATE scenes SET {assignments} WHERE id = :id", {**fields, "id": scene_id}
        )


def set_scene_audio(
    scene_id: str,
    *,
    synth_hash: str | None,
    raw_duration_sec: float | None,
    duration_sec: float | None,
    error: str | None,
) -> None:
    with write() as conn:
        conn.execute(
            """
            UPDATE scenes
               SET synth_hash = ?, raw_duration_sec = ?, duration_sec = ?, error = ?, updated_at = ?
             WHERE id = ?
            """,
            (synth_hash, raw_duration_sec, duration_sec, error, now(), scene_id),
        )


def delete_scene(scene_id: str) -> None:
    with write() as conn:
        conn.execute("DELETE FROM scenes WHERE id = ?", (scene_id,))


def replace_scenes(project_id: str, scenes: list[dict]) -> None:
    """스크립트를 다시 파싱했을 때 씬 전체를 갈아끼운다."""
    with write() as conn:
        conn.execute("DELETE FROM scenes WHERE project_id = ?", (project_id,))
        for position, scene in enumerate(scenes):
            row: dict[str, Any] = {
                "id": new_id(),
                "project_id": project_id,
                "position": position,
                "updated_at": now(),
            }
            for field in _SCENE_FIELDS:
                row[field] = scene.get(field)
            row["text"] = scene.get("text") or ""
            columns = ", ".join(row)
            placeholders = ", ".join(f":{k}" for k in row)
            conn.execute(f"INSERT INTO scenes ({columns}) VALUES ({placeholders})", row)


def reorder_scenes(project_id: str, ordered_ids: list[str]) -> None:
    with write() as conn:
        for position, scene_id in enumerate(ordered_ids):
            conn.execute(
                "UPDATE scenes SET position = ?, updated_at = ? WHERE id = ? AND project_id = ?",
                (position, now(), scene_id, project_id),
            )


def compact_positions(project_id: str) -> None:
    """씬 삭제 후 position 을 0..n-1 로 다시 매긴다."""
    with write() as conn:
        rows = conn.execute(
            "SELECT id FROM scenes WHERE project_id = ? ORDER BY position", (project_id,)
        ).fetchall()
        for position, row in enumerate(rows):
            conn.execute("UPDATE scenes SET position = ? WHERE id = ?", (position, row["id"]))


# ── 보이스 ──────────────────────────────────────────────────────────────────


def create_voice(name: str, filename: str, duration_sec: float) -> str:
    voice_id = new_id()
    with write() as conn:
        conn.execute(
            "INSERT INTO voices (id, name, filename, duration_sec, created_at) VALUES (?,?,?,?,?)",
            (voice_id, name, filename, duration_sec, now()),
        )
    return voice_id


def list_voices() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM voices ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_voice(voice_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM voices WHERE id = ?", (voice_id,)).fetchone()
    return dict(row) if row else None


def delete_voice(voice_id: str) -> None:
    with write() as conn:
        conn.execute("DELETE FROM voices WHERE id = ?", (voice_id,))


def voice_path(voice: dict) -> Path:
    return config.VOICES_DIR / voice["filename"]


# ── 발음 사전 (전역) ────────────────────────────────────────────────────────


def list_dictionary() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM dictionary ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def dictionary_pairs() -> list[tuple[str, str]]:
    return [(e["source"], e["target"]) for e in list_dictionary()]


def create_dictionary_entry(source: str, target: str) -> str:
    entry_id = new_id()
    with write() as conn:
        conn.execute(
            "INSERT INTO dictionary (id, source, target, created_at) VALUES (?,?,?,?)",
            (entry_id, source, target, now()),
        )
    return entry_id


def update_dictionary_entry(entry_id: str, source: str, target: str) -> None:
    with write() as conn:
        conn.execute(
            "UPDATE dictionary SET source = ?, target = ? WHERE id = ?", (source, target, entry_id)
        )


def delete_dictionary_entry(entry_id: str) -> None:
    with write() as conn:
        conn.execute("DELETE FROM dictionary WHERE id = ?", (entry_id,))


# ── 작업 ────────────────────────────────────────────────────────────────────


def create_job(project_id: str, kind: str, total: int) -> str:
    job_id = new_id()
    ts = now()
    with write() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, project_id, kind, status, total, done, created_at, updated_at)
            VALUES (?,?,?,'queued',?,0,?,?)
            """,
            (job_id, project_id, kind, total, ts, ts),
        )
    return job_id


def update_job(job_id: str, **patch: Any) -> None:
    allowed = {"status", "total", "done", "current", "error", "result"}
    fields = {k: v for k, v in patch.items() if k in allowed}
    if not fields:
        return
    if isinstance(fields.get("result"), (dict, list)):
        fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
    fields["updated_at"] = now()
    assignments = ", ".join(f"{k} = :{k}" for k in fields)
    with write() as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = :id", {**fields, "id": job_id})


def get_job(job_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = dict(row)
    if job.get("result"):
        try:
            job["result"] = json.loads(job["result"])
        except json.JSONDecodeError:
            pass
    return job


def latest_job(project_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM jobs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    return get_job(row["id"]) if row else None


# ── 합성 해시 ───────────────────────────────────────────────────────────────


def synth_hash(
    *,
    engine: str,
    language: str,
    normalized_text: str,
    voice_id: str | None,
    exaggeration: float,
    cfg_weight: float,
    temperature: float,
) -> str:
    """GPU 재합성이 필요한지 판정하는 지문.

    속도(speed)와 무음 간격은 여기 들어가지 않는다 — 그건 ffmpeg 후처리라 원본 wav 를
    재사용해 다시 렌더링하면 되고, 모델을 다시 돌릴 이유가 없다.
    """
    payload = "\x1f".join(
        [
            engine,
            language,
            normalized_text,
            voice_id or "-",
            f"{exaggeration:.3f}",
            f"{cfg_weight:.3f}",
            f"{temperature:.3f}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
