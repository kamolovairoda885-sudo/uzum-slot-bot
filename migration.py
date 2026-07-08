python - <<'PY'
import os, json, psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL topilmadi")

with open("backup_export.json", "r", encoding="utf-8") as f:
    data = json.load(f)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    full_name TEXT,
    username TEXT,
    stars INTEGER DEFAULT 1,
    is_blocked INTEGER DEFAULT 0,
    created_at TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS stores (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT,
    store_id TEXT,
    store_name TEXT,
    created_at TEXT,
    UNIQUE (telegram_id, store_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS bookings (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT,
    store_id TEXT,
    store_name TEXT,
    invoice TEXT,
    date TEXT,
    status TEXT,
    result TEXT,
    created_at TEXT
)
""")

for u in data.get("users", []):
    cur.execute("""
    INSERT INTO users (telegram_id, full_name, username, stars, is_blocked, created_at)
    VALUES (%s,%s,%s,%s,%s,%s)
    ON CONFLICT (telegram_id) DO UPDATE SET
        full_name=EXCLUDED.full_name,
        username=EXCLUDED.username,
        stars=EXCLUDED.stars,
        is_blocked=EXCLUDED.is_blocked,
        created_at=EXCLUDED.created_at
    """, (
        u.get("telegram_id"), u.get("full_name"), u.get("username"),
        u.get("stars", 1), u.get("is_blocked", 0), u.get("created_at")
    ))

for s in data.get("stores", []):
    cur.execute("""
    INSERT INTO stores (telegram_id, store_id, store_name, created_at)
    VALUES (%s,%s,%s,%s)
    ON CONFLICT (telegram_id, store_id) DO UPDATE SET
        store_name=EXCLUDED.store_name,
        created_at=EXCLUDED.created_at
    """, (
        s.get("telegram_id"), s.get("store_id"),
        s.get("store_name"), s.get("created_at")
    ))

for b in data.get("bookings", []):
    cur.execute("""
    INSERT INTO bookings (telegram_id, store_id, store_name, invoice, date, status, result, created_at)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        b.get("telegram_id"), b.get("store_id"), b.get("store_name"),
        b.get("invoice"), b.get("date"), b.get("status"),
        b.get("result"), b.get("created_at")
    ))

conn.commit()

for table in ["users", "stores", "bookings"]:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(table, cur.fetchone()[0])

cur.close()
conn.close()
print("OK: SQLite ma'lumotlari PostgreSQL'ga ko'chirildi")
PY
