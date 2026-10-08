"""read_document tool: reads a file from DOCUMENTS_DIR only. Path traversal is
refused here in the tool itself; whether the call should happen at all is the
gate's decision."""
from __future__ import annotations

import os


def read_document(filename: str) -> dict:
    docs = os.path.realpath(os.environ.get("DOCUMENTS_DIR", "./demo/documents"))
    path = os.path.realpath(os.path.join(docs, filename))
    if not path.startswith(docs + os.sep):
        return {"status": "refused", "reason": "path outside the documents directory"}
    if not os.path.isfile(path):
        return {"status": "not_found", "filename": filename}
    with open(path, encoding="utf-8", errors="replace") as f:
        return {"status": "ok", "filename": filename, "content": f.read(20000)}
