"""Promote 'admin' to admin, back up DB, then delete 'demo' with full cascade."""
import asyncio
import sqlite3
import subprocess
import sys

sys.path.insert(0, r"D:\ai\code\lifeos\apps\server")

DB = r"D:\ai\code\lifeos\data\lifeos.db"


async def main():
    # 1) promote admin
    conn = sqlite3.connect(DB)
    conn.execute("UPDATE users SET is_admin = 1 WHERE username = 'admin'")
    conn.commit()
    print("admin promoted")
    conn.close()

    # 2) backup via VACUUM INTO
    conn = sqlite3.connect(DB)
    conn.execute("VACUUM INTO ?", (r"D:\ai\code\lifeos\data\backups\pre-demo-delete.db",))
    conn.close()
    print("backup done")

    # 3) delete demo via app cascade
    from app.db import SessionLocal, init_db
    from app.models import User
    from app.api.auth import _delete_user_data
    from sqlalchemy import select

    await init_db()
    async with SessionLocal() as db:
        demo = (await db.execute(select(User).where(User.username == "demo"))).scalar_one()
        await _delete_user_data(db, demo.id)
        await db.delete(demo)
        await db.commit()
    print("demo deleted")


asyncio.run(main())
