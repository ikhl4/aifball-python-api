"""Durable Dify jobs for the Render AiFBall service.

Enable only after setting DATABASE_URL, CHAT_JOBS_TOKEN and DIFY_API_KEY.
The job worker is independent of the requesting browser. Postgres retains
jobs across web process restarts. Run a single Render instance for this
prototype; for horizontal scaling use a dedicated worker/queue.
"""
import json
import logging
import os
import secrets
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta

import psycopg
from psycopg.rows import dict_row
import requests
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("aifball.chat_jobs")
router = APIRouter(prefix="/internal/chat-jobs", tags=["internal-chat-jobs"])
_stop = threading.Event()
_worker = None
DATABASE_URL = os.getenv("DATABASE_URL", "")
CHAT_JOBS_TOKEN = os.getenv("CHAT_JOBS_TOKEN", "")
DIFY_API_KEY = os.getenv("DIFY_API_KEY", "")


def enabled():
    return bool(DATABASE_URL and CHAT_JOBS_TOKEN and DIFY_API_KEY)


def authorize(authorization: str | None):
    if not enabled():
        raise HTTPException(503, "Background chat jobs are not configured")
    expected = "Bearer " + CHAT_JOBS_TOKEN
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, "Unauthorized")


def connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)


def init_db():
    with connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS aifball_chat_jobs (
                id UUID PRIMARY KEY,
                owner TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                query TEXT NOT NULL,
                conversation_id TEXT NOT NULL DEFAULT '',
                answer TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'queued',
                error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (owner, idempotency_key)
            )
        """)
        # Recover jobs interrupted by a Render restart.
        conn.execute("UPDATE aifball_chat_jobs SET status='queued', updated_at=now() WHERE status='running'")


class NewJob(BaseModel):
    owner: str = Field(min_length=1, max_length=160)
    idempotency_key: str = Field(min_length=8, max_length=160)
    query: str = Field(min_length=1, max_length=12000)
    conversation_id: str = Field(default="", max_length=300)


def public(row):
    return {k: row[k] for k in ("id", "status", "answer", "conversation_id", "error", "created_at", "updated_at")}


@router.post("")
def submit_job(payload: NewJob, authorization: str | None = Header(default=None)):
    authorize(authorization)
    with connect() as conn:
        row = conn.execute("""
            INSERT INTO aifball_chat_jobs (id, owner, idempotency_key, query, conversation_id)
            VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (owner,idempotency_key) DO UPDATE
            SET updated_at=aifball_chat_jobs.updated_at
            RETURNING *
        """, (uuid.uuid4(), payload.owner, payload.idempotency_key, payload.query, payload.conversation_id)).fetchone()
    return public(row)


@router.get("/{job_id}")
def get_job(job_id: uuid.UUID, owner: str, authorization: str | None = Header(default=None)):
    authorize(authorization)
    with connect() as conn:
        row = conn.execute("SELECT * FROM aifball_chat_jobs WHERE id=%s AND owner=%s", (job_id, owner)).fetchone()
    if not row:
        raise HTTPException(404, "Job not found")
    return public(row)


def update(job_id, **fields):
    assignments = ", ".join(f"{name}=%s" for name in fields)
    with connect() as conn:
        conn.execute(f"UPDATE aifball_chat_jobs SET {assignments}, updated_at=now() WHERE id=%s",
                     (*fields.values(), job_id))


def process_job(job):
    answer = ""
    conversation = job["conversation_id"]
    try:
        with requests.post(
            "https://api.dify.ai/v1/chat-messages",
            headers={"Authorization": "Bearer " + DIFY_API_KEY, "Content-Type": "application/json"},
            json={"inputs": {}, "query": job["query"], "response_mode": "streaming",
                  "conversation_id": conversation or None, "user": "aifball-" + job["owner"]},
            stream=True, timeout=(15, 300),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if _stop.is_set():
                    raise RuntimeError("Worker stopping")
                if not line or not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[6:])
                except (ValueError, TypeError):
                    continue
                if event.get("conversation_id"):
                    conversation = event["conversation_id"]
                if event.get("event") in ("message", "agent_message"):
                    answer += event.get("answer") or ""
                    update(job["id"], answer=answer, conversation_id=conversation)
                if event.get("event") == "error":
                    raise RuntimeError("Dify reported an error")
                if event.get("event") == "message_end":
                    update(job["id"], status="completed", answer=answer, conversation_id=conversation)
                    return
        raise RuntimeError("Dify stream ended without message_end")
    except Exception:
        logger.exception("Background chat job failed: %s", job["id"])
        update(job["id"], status="failed", answer=answer, conversation_id=conversation,
               error="تعذر إكمال البحث. حاول مرة أخرى.")


def worker_loop():
    while not _stop.is_set():
        try:
            with connect() as conn:
                job = conn.execute("""
                    UPDATE aifball_chat_jobs SET status='running', updated_at=now()
                    WHERE id = (
                      SELECT id FROM aifball_chat_jobs WHERE status='queued'
                      ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED
                    ) RETURNING *
                """).fetchone()
            if job:
                process_job(job)
            else:
                _stop.wait(1.5)
        except Exception:
            logger.exception("Background job worker error")
            _stop.wait(5)


def start_worker():
    global _worker
    if not enabled():
        logger.warning("Chat jobs disabled: DATABASE_URL, CHAT_JOBS_TOKEN or DIFY_API_KEY missing")
        return
    init_db()
    _stop.clear()
    _worker = threading.Thread(target=worker_loop, name="aifball-chat-worker", daemon=True)
    _worker.start()


def stop_worker():
    _stop.set()
    if _worker:
        _worker.join(timeout=2)
