import os
import sys
import psycopg
from psycopg.rows import dict_row

DDL = """
CREATE TABLE IF NOT EXISTS people (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  email TEXT UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

def get_db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set.")
        sys.exit(1)
    return url


def main() -> None:
    url = get_db_url()

    # Open the database connection
    with psycopg.connect(url) as conn:
        # 1️⃣ Ensure table exists
        with conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()

        # 2️⃣ Upsert a demo record
        name = "Ada Lovelace"
        email = "ada@example.com"
        upsert_sql = """
        INSERT INTO people (name, email)
        VALUES (%s, %s)
        ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
        RETURNING id, name, email, created_at;
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(upsert_sql, (name, email))
            inserted = cur.fetchone()
            print("Upserted:", inserted)
            conn.commit()

        # 3️⃣ Read back all rows
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name, email, created_at FROM people ORDER BY id;")
            rows = cur.fetchall()

            print("\nPeople in database:")
            for r in rows:
                print(f"{r['id']}: {r['name']} ({r['email']}) @ {r['created_at']}")


if __name__ == "__main__":
    main()
