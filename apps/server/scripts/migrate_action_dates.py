"""One-off migration: actions.date legacy datetime strings -> date-only (v1.1)."""
import sqlite3

DB = r"D:\ai\code\lifeos\data\lifeos.db"

conn = sqlite3.connect(DB)
cur = conn.execute("SELECT id, date FROM actions")
rows = cur.fetchall()
fixed = 0
for aid, d in rows:
    if d and len(d) > 10:  # '2026-10-18 00:00:00.000000' -> '2026-10-18'
        conn.execute("UPDATE actions SET date = ? WHERE id = ?", (d[:10], aid))
        fixed += 1
conn.commit()
conn.close()
print(f"actions total={len(rows)}, migrated={fixed}")
