"""Isolated two-agent communication proof of concept.

No LLM calls and no filesystem/terminal tools: this exercises reliable message
delivery, concurrent worker availability, traceable replies, and persisted status.
NOT a production multi-process message broker or a LangGraph implementation.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(prefix="/api/poc-collaboration", tags=["poc-collaboration"])
AGENTS = ("developer", "tester")
POLL_SECONDS = 0.15


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MessageInput(BaseModel):
    sender: Literal["user"] = "user"
    recipient: str = Field(pattern="^(developer|tester)$")
    content: str = Field(min_length=1, max_length=4000)


class DemoStart(BaseModel):
    task: str = Field(default="Build and test a login API", min_length=1, max_length=1000)


class CollaborationPOC:
    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._stop = threading.Event()
        self._threads: dict[str, threading.Thread] = {}
        self._initialize()

    def _db(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS poc_messages (
                id TEXT PRIMARY KEY, sender TEXT NOT NULL, recipient TEXT NOT NULL,
                content TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                processed_at TEXT, response_to TEXT
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS poc_activity (
                agent TEXT PRIMARY KEY, phase TEXT NOT NULL, latest TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            for agent in AGENTS:
                db.execute(
                    "INSERT OR IGNORE INTO poc_activity VALUES (?, ?, ?, ?)",
                    (agent, "idle", "No messages processed yet", _now()),
                )

    def post(self, sender: str, recipient: str, content: str, response_to: str | None = None) -> str:
        if sender not in ("user", *AGENTS) or recipient not in AGENTS:
            raise ValueError("Unknown sender or recipient")
        message_id = str(uuid4())
        with self._db() as db:
            db.execute(
                """INSERT INTO poc_messages
                (id, sender, recipient, content, status, created_at, response_to)
                VALUES (?, ?, ?, ?, 'queued', ?, ?)""",
                (message_id, sender, recipient, content, _now(), response_to),
            )
        return message_id

    def _claim(self, agent: str) -> dict | None:
        # BEGIN IMMEDIATE ensures only one worker can claim a queued message.
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT * FROM poc_messages
                   WHERE recipient=? AND status='queued'
                   ORDER BY created_at, rowid LIMIT 1""", (agent,)
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE poc_messages SET status='processing' WHERE id=?", (row["id"],))
            return dict(row)

    def _activity(self, agent: str, phase: str, latest: str) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE poc_activity SET phase=?, latest=?, updated_at=? WHERE agent=?",
                (phase, latest, _now(), agent),
            )

    def _handle(self, agent: str, message: dict) -> None:
        text = message["content"]
        self._activity(agent, "working", "Processing message " + message["id"])
        # A scripted response proves routing; it is not an LLM-generated answer.
        if agent == "developer" and message["sender"] == "user" and "start demo" in text.lower():
            self.post("developer", "tester", "Login API implementation ready; please test it.", message["id"])
            summary = "Developer handed the implementation to Tester."
        elif agent == "tester" and message["sender"] == "developer":
            self.post("tester", "developer", "Test report: authentication test failed (demo fixture). Please investigate.", message["id"])
            summary = "Tester sent a failure report directly to Developer."
        elif agent == "developer" and message["sender"] == "tester":
            summary = "Developer received Tester feedback: " + text
        else:
            summary = agent.capitalize() + " received from " + message["sender"] + ": " + text
        with self._db() as db:
            db.execute(
                "UPDATE poc_messages SET status='processed', processed_at=? WHERE id=?",
                (_now(), message["id"]),
            )
        self._activity(agent, "idle", summary)

    def _work(self, agent: str) -> None:
        while not self._stop.is_set():
            try:
                message = self._claim(agent)
                if message:
                    self._handle(agent, message)
                else:
                    self._stop.wait(POLL_SECONDS)
            except Exception as exc:
                self._activity(agent, "error", str(exc))
                self._stop.wait(0.5)

    def start(self) -> None:
        self._stop.clear()
        for agent in AGENTS:
            thread = self._threads.get(agent)
            if thread is None or not thread.is_alive():
                thread = threading.Thread(target=self._work, args=(agent,), daemon=True, name="poc-" + agent)
                self._threads[agent] = thread
                thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads.values():
            if thread.is_alive():
                thread.join(timeout=2)

    def snapshot(self) -> dict:
        with self._db() as db:
            messages = [dict(row) for row in db.execute(
                "SELECT * FROM poc_messages ORDER BY created_at, rowid"
            ).fetchall()]
            agents = [dict(row) for row in db.execute(
                "SELECT * FROM poc_activity ORDER BY agent"
            ).fetchall()]
        return {"agents": agents, "messages": messages, "running": {
            agent: bool(self._threads.get(agent) and self._threads[agent].is_alive())
            for agent in AGENTS
        }}


poc = CollaborationPOC(settings.data_dir / "poc-collaboration.sqlite3")


@router.post("/start")
def start_poc(body: DemoStart) -> dict:
    poc.start()
    message_id = poc.post("user", "developer", "START DEMO: " + body.task)
    return {"message_id": message_id, "status": "queued", "note": "Scripted demo; no LLM or tools executed."}


@router.post("/messages")
def send_message(body: MessageInput) -> dict:
    poc.start()
    message_id = poc.post(body.sender, body.recipient, body.content)
    return {"message_id": message_id, "status": "queued"}


@router.get("/status")
def get_status() -> dict:
    return poc.snapshot()


@router.post("/stop")
def stop_poc() -> dict:
    poc.stop()
    return {"status": "stopped"}
