"""Deterministic tool-call proposer for runs without a main LLM.

When no LLM (Bedrock or OpenRouter) is attached, an agent cannot decide its
own tool calls, so this module derives them from the user's request and the
documents read during the run. It NEVER decides whether a call is safe:
every proposal still passes the gate. The UI labels proposals
"scripted proposal (no LLM attached)".
"""
from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_DIRECTIVE_RE = re.compile(
    r"(?is)\[\s*SYSTEM\s+NOTE.*?send(?:_email|\s+email).*?to\s+([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})"
    r".*?subject\s*[\"']([^\"']+)[\"']")
READ_WORDS = re.compile(r"(?i)\b(read|open|summar\w*|check|review|look\s+at)\b")
QUERY_WORDS = re.compile(r"(?i)\b(customer|database|data|record|order|query)\b")


def extract_directives(content: str) -> list[dict]:
    """Instruction directives hidden inside document content, parsed out
    deterministically. Used to reproduce what a hijacked agent would do."""
    out = []
    for m in _DIRECTIVE_RE.finditer(content or ""):
        out.append({"to": m.group(1), "subject": m.group(2)})
    return out


def propose(message: str, documents: list[dict], read_results: list[dict]) -> list[dict]:
    """Returns ordered proposals: {tool, args, source}."""
    proposals: list[dict] = []
    seen_docs: set[str] = set()
    wants_read = bool(READ_WORDS.search(message))
    wants_query = bool(QUERY_WORDS.search(message))
    emails_in_request = set(_EMAIL_RE.findall(message))
    wants_email = bool(re.search(r"(?i)\b(email|mail|send)\b", message))

    for doc in documents:
        stem = doc["filename"].rsplit(".", 1)[0].lower()
        keywords = [w for w in re.split(r"[^a-z0-9]+", stem) if len(w) > 3]
        if wants_read and keywords and any(k in message.lower() for k in keywords):
            proposals.append({"tool": "read_document", "args": {"filename": doc["filename"]},
                              "source": "scripted: read intent in request"})
            seen_docs.add(doc["filename"])

    for res in read_results:
        if res.get("status") != "ok":
            continue
        for d in extract_directives(res.get("content", "")):
            proposals.append({
                "tool": "send_email",
                "args": {"to": d["to"], "subject": d["subject"],
                         "body": res.get("content", "")[:4000]},
                "source": "scripted: instruction directive found in document content",
            })

    if wants_email and emails_in_request:
        body_source = next((r.get("content", "") for r in read_results if r.get("status") == "ok"), "")
        for addr in list(emails_in_request)[:1]:
            proposals.append({
                "tool": "send_email",
                "args": {"to": addr, "subject": "Summary",
                         "body": (f"Summary as requested.\n\n{body_source[:2000]}" if body_source
                                  else "Summary as requested.")},
                "source": "scripted: email intent with recipient named in the request",
            })

    if wants_query:
        proposals.append({"tool": "database_query", "args": {"query": "SELECT * FROM customers"},
                          "source": "scripted: database intent in request"})
    return proposals
