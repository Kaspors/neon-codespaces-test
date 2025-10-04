import os, pathlib, psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise SystemExit("DATABASE_URL missing in .env")

schema_path = pathlib.Path(__file__).parent.parent / "app" / "schema.sql"
sql = schema_path.read_text()

with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
        # Seed minimal data if empty
        cur.execute("SELECT count(*) AS c FROM users;")
        if cur.fetchone()["c"] == 0:
            cur.execute("""
                INSERT INTO users (name, email, role) VALUES
                ('Admin User', 'admin@example.com', 'admin'),
                ('Project Lead', 'lead@example.com', 'lead'),
                ('Finance Person', 'finance@example.com', 'finance'),
                ('Contributor One', 'contrib@example.com', 'contributor');
            """)
        cur.execute("SELECT count(*) AS c FROM clients;")
        if cur.fetchone()["c"] == 0:
            cur.execute("INSERT INTO clients (name, currency) VALUES ('Acme A/S','DKK');")
        cur.execute("SELECT id FROM clients LIMIT 1;")
        client_id = cur.fetchone()["id"]

        cur.execute("SELECT count(*) AS c FROM projects;")
        if cur.fetchone()["c"] == 0:
            # Get lead id
            cur.execute("SELECT id FROM users WHERE email='lead@example.com';")
            lead_id = cur.fetchone()["id"]
            cur.execute("""
                INSERT INTO projects (client_id, code, name, start_date, status, approver_user_id)
                VALUES (%s, 'ACM-001', 'Athene POC', CURRENT_DATE, 'active', %s)
                RETURNING id;
            """, (client_id, lead_id))
            project_id = cur.fetchone()["id"]
            cur.execute("""
                INSERT INTO tasks (project_id, name, billable_default)
                VALUES (%s,'Analysis',true), (%s,'Development',true), (%s,'Meetings',false);
            """, (project_id, project_id, project_id))
            # Assign contributor
            cur.execute("SELECT id FROM users WHERE email='contrib@example.com';")
            contrib_id = cur.fetchone()["id"]
            cur.execute("INSERT INTO project_assignments (project_id, user_id) VALUES (%s,%s) ON CONFLICT DO NOTHING;", (project_id, contrib_id))
    conn.commit()

print("DB initialized & seeded ✅")
