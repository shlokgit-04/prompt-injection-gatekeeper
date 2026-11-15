"""SQLite store: users, per-user audit, approvals, messages, outbox, policy."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL,
  token_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ts TEXT NOT NULL,
  tool TEXT NOT NULL, args_json TEXT NOT NULL, execution TEXT NOT NULL,
  outcome TEXT NOT NULL, decision_json TEXT, approval_id TEXT);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, ts TEXT NOT NULL, tool TEXT NOT NULL,
  args_json TEXT NOT NULL, decision_json TEXT NOT NULL, status TEXT NOT NULL,
  resolved_at TEXT);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ts TEXT NOT NULL,
  role TEXT NOT NULL, content TEXT NOT NULL, meta_json TEXT);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, ts TEXT NOT NULL,
  recipient TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policy (
  user_id INTEGER PRIMARY KEY, deny_risk REAL NOT NULL, confirm_risk REAL NOT NULL,
  confirm_grounding REAL NOT NULL, deny_grounding REAL NOT NULL,
  confirm_premature REAL NOT NULL);
"""

DEFAULT_POLICY = {"deny_risk": 0.75, "confirm_risk": 0.55, "confirm_grounding": 0.55,
                  "deny_grounding": 0.20, "confirm_premature": 0.60}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Store:
    def __init__(self, path: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    # -- users -------------------------------------------------------------
    def create_user(self, email: str, pw_hash: str) -> int:
        try:
            cur = self._exec("INSERT INTO users (email, pw_hash, created_at) VALUES (?,?,?)",
                             (email, pw_hash, now()))
            uid = cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError("email already registered") from None
        self._exec("INSERT INTO policy (user_id, deny_risk, confirm_risk, confirm_grounding, deny_grounding, confirm_premature) VALUES (?,?,?,?,?,?)",
                   (uid, *DEFAULT_POLICY.values()))
        return uid

    def user_by_email(self, email: str) -> dict | None:
        row = self._exec("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        return dict(row) if row else None

    def user_by_id(self, uid: int) -> dict | None:
        row = self._exec("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return dict(row) if row else None

    def bump_token_version(self, uid: int) -> None:
        self._exec("UPDATE users SET token_version = token_version + 1 WHERE id=?", (uid,))

    def delete_user(self, uid: int) -> None:
        for table in ("audit_events", "approvals", "messages", "outbox", "policy"):
            self._exec(f"DELETE FROM {table} WHERE user_id=?", (uid,))
        self._exec("DELETE FROM users WHERE id=?", (uid,))

    # -- audit ---------------------------------------------------------------
    def audit_record(self, uid: int, tool: str, args: dict, execution: str,
                     outcome: str, decision: dict | None = None,
                     approval_id: str | None = None) -> dict:
        event = {"timestamp": now(), "tool": tool, "arguments": args,
                 "execution": execution, "outcome": outcome}
        if decision:
            event["decision"] = decision
        if approval_id:
            event["approval_id"] = approval_id
        self._exec(
            "INSERT INTO audit_events (user_id, ts, tool, args_json, execution, outcome, decision_json, approval_id) VALUES (?,?,?,?,?,?,?,?)",
            (uid, event["timestamp"], tool, json.dumps(args), execution, outcome,
             json.dumps(decision) if decision else None, approval_id))
        return event

    def audit_recent(self, uid: int, limit: int = 100) -> list[dict]:
        rows = self._exec(
            "SELECT ts, tool, args_json, execution, outcome, decision_json, approval_id FROM audit_events WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (uid, max(1, min(limit, 500)))).fetchall()
        out = []
        for r in rows:
            e = {"timestamp": r["ts"], "tool": r["tool"], "arguments": json.loads(r["args_json"]),
                 "execution": r["execution"], "outcome": r["outcome"]}
            if r["decision_json"]:
                e["decision"] = json.loads(r["decision_json"])
            if r["approval_id"]:
                e["approval_id"] = r["approval_id"]
            out.append(e)
        return out

    # -- approvals -----------------------------------------------------------
    def approval_enqueue(self, uid: int, approval_id: str, tool: str, args: dict,
                         decision: dict) -> None:
        self._exec("INSERT INTO approvals (id, user_id, ts, tool, args_json, decision_json, status) VALUES (?,?,?,?,?,?,'pending')",
                   (approval_id, uid, now(), tool, json.dumps(args), json.dumps(decision)))

    def approvals_pending(self, uid: int) -> list[dict]:
        rows = self._exec("SELECT * FROM approvals WHERE user_id=? AND status='pending' ORDER BY id",
                          (uid,)).fetchall()
        return [self._approval_row(r) for r in rows]

    def approval_get(self, uid: int, approval_id: str) -> dict | None:
        row = self._exec("SELECT * FROM approvals WHERE user_id=? AND id=?", (uid, approval_id)).fetchone()
        return self._approval_row(row) if row else None

    def approval_resolve(self, uid: int, approval_id: str, approve: bool) -> dict | None:
        row = self._exec("SELECT * FROM approvals WHERE user_id=? AND id=? AND status='pending'",
                         (uid, approval_id)).fetchone()
        if not row:
            return None
        status = "approved" if approve else "rejected"
        self._exec("UPDATE approvals SET status=?, resolved_at=? WHERE id=?", (status, now(), approval_id))
        return self._approval_row(row)

    @staticmethod
    def _approval_row(r: sqlite3.Row) -> dict:
        return {"id": r["id"], "tool": r["tool"], "arguments": json.loads(r["args_json"]),
                "decision": json.loads(r["decision_json"]), "status": r["status"],
                "ts": r["ts"]}

    # -- messages ------------------------------------------------------------
    def message_add(self, uid: int, role: str, content: str, meta: dict | None = None) -> None:
        self._exec("INSERT INTO messages (user_id, ts, role, content, meta_json) VALUES (?,?,?,?,?)",
                   (uid, now(), role, content, json.dumps(meta) if meta else None))

    def messages_recent(self, uid: int, limit: int = 20) -> list[dict]:
        rows = self._exec("SELECT ts, role, content, meta_json FROM messages WHERE user_id=? ORDER BY id DESC LIMIT ?",
                          (uid, max(1, min(limit, 100)))).fetchall()
        return [{"ts": r["ts"], "role": r["role"], "content": r["content"],
                 **({"meta": json.loads(r["meta_json"])} if r["meta_json"] else {})}
                for r in reversed(rows)]

    # -- outbox --------------------------------------------------------------
    def outbox_add(self, uid: int, recipient: str, subject: str, body: str) -> None:
        self._exec("INSERT INTO outbox (user_id, ts, recipient, subject, body) VALUES (?,?,?,?,?)",
                   (uid, now(), recipient, subject, body))

    def outbox_recent(self, uid: int, limit: int = 50) -> list[dict]:
        rows = self._exec("SELECT ts, recipient, subject, body FROM outbox WHERE user_id=? ORDER BY id DESC LIMIT ?",
                          (uid, max(1, min(limit, 200)))).fetchall()
        return [dict(r) for r in rows]

    # -- policy --------------------------------------------------------------
    def policy_get(self, uid: int) -> dict:
        row = self._exec("SELECT * FROM policy WHERE user_id=?", (uid,)).fetchone()
        if not row:
            return dict(DEFAULT_POLICY)
        return {k: row[k] for k in DEFAULT_POLICY}

    def policy_set(self, uid: int, values: dict) -> dict:
        current = self.policy_get(uid)
        for k, v in values.items():
            if k in current and isinstance(v, (int, float)):
                current[k] = round(min(0.95, max(0.05, float(v))), 4)
        self._exec("UPDATE policy SET deny_risk=?, confirm_risk=?, confirm_grounding=?, deny_grounding=?, confirm_premature=? WHERE user_id=?",
                   (current["deny_risk"], current["confirm_risk"], current["confirm_grounding"],
                    current["deny_grounding"], current["confirm_premature"], uid))
        return current
