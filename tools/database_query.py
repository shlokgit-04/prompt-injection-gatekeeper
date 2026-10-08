"""database_query tool: read-only SELECT against a small SQLite store. Only
SELECT statements run; anything else is refused by the tool itself."""
from __future__ import annotations

import os
import sqlite3


def database_query(query: str) -> dict:
    q = query.strip().rstrip(";").strip()
    if not q.lower().startswith("select"):
        return {"status": "refused", "reason": "only SELECT statements are allowed"}
    db = os.path.join(os.environ.get("DATA_DIR", "./data"), "customers.db")
    if not os.path.exists(db):
        return {"status": "no_database", "hint": "run scripts/seed_demo_data.sh first"}
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(q).fetchmany(50)
        cols = [d[0] for d in conn.execute(q).description] if rows or True else []
    except sqlite3.Error as e:
        return {"status": "error", "reason": str(e)}
    finally:
        conn.close()
    return {"status": "ok", "columns": cols, "rows": rows}
