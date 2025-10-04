import os
import sys
from typing import List, Dict

from flask import Flask, render_template, request, redirect, url_for, flash
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
        print("ERROR: DATABASE_URL not set. Add it as a Codespaces secret and rebuild container.")
        sys.exit(1)
    return url

def ensure_table():
    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")  # ok for demo

ensure_table()

@app.get("/")
def index():
    # list all people
    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name, email, created_at FROM people ORDER BY id DESC;")
            rows: List[Dict] = cur.fetchall()
    return render_template("index.html", rows=rows)

@app.post("/add")
def add():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip() or None

    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("index"))

    sql = """
    INSERT INTO people (name, email)
    VALUES (%s, %s)
    ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name
    RETURNING id;
    """
    try:
        with psycopg.connect(get_db_url()) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (name, email))
                conn.commit()
        flash("Saved ✔️", "success")
    except Exception as e:
        flash(f"Insert failed: {e}", "error")
    return redirect(url_for("index"))

@app.post("/delete/<int:person_id>")
def delete(person_id: int):
    try:
        with psycopg.connect(get_db_url()) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM people WHERE id = %s;", (person_id,))
                conn.commit()
        flash("Deleted 🗑️", "success")
    except Exception as e:
        flash(f"Delete failed: {e}", "error")
    return redirect(url_for("index"))

# Optional: quick reset route (drop & recreate). Comment out in real life.
@app.post("/reset")
def reset():
    try:
        with psycopg.connect(get_db_url()) as conn:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS people;")
                cur.execute(DDL)
                conn.commit()
        flash("Table reset ✅", "success")
    except Exception as e:
        flash(f"Reset failed: {e}", "error")
    return redirect(url_for("index"))

if __name__ == "__main__":
    # Run on 0.0.0.0 so Codespaces can forward the port
    app.run(host="0.0.0.0", port=8000, debug=True)
