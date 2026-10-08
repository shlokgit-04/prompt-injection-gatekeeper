#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 - <<'PY'
import sqlite3, os
os.makedirs("data", exist_ok=True)
conn = sqlite3.connect("data/customers.db")
conn.executescript("""
CREATE TABLE IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT, company TEXT, email TEXT);
CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, customer_id INTEGER, item TEXT, amount REAL);
INSERT INTO customers VALUES (1,'Asha Sharma','Nimbus Logistics','asha@nimbus.example');
INSERT INTO customers VALUES (2,'Ravi Menon','Peak Foods','ravi@peakfoods.example');
INSERT INTO orders VALUES (101,1,'pallet racking',12000.00);
INSERT INTO orders VALUES (102,2,'cold-chain sensors',8400.00);
""")
conn.commit(); conn.close()
print("seeded data/customers.db")
PY
