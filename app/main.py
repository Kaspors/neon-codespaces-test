# app/main.py
import os
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette import status
from jinja2.exceptions import TemplateNotFound

import psycopg
from psycopg.rows import dict_row

# ---------- DB helpers ----------
def db_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        raise RuntimeError("DATABASE_URL not set")
    return url

def connect():
    # Force search_path to public so we always see the expected schema/tables
    conn = psycopg.connect(db_url())
    with conn.cursor() as cur:
        cur.execute("SET search_path TO public;")
    return conn

def iso_week_dates(year: int, week: int) -> List[date]:
    monday = date.fromisocalendar(year, week, 1)
    return [monday + timedelta(days=i) for i in range(7)]

def pick_default_person_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM v2_people ORDER BY id LIMIT 1;")
        row = cur.fetchone()
        if not row:
            raise RuntimeError("No v2_people in DB")
        return int(row[0])

def ensure_v2_schema() -> None:
    """Create isolated v2 tables (no touching old tables) + seed minimal data."""
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS v2_people (
                  id BIGSERIAL PRIMARY KEY,
                  name TEXT NOT NULL,
                  email TEXT UNIQUE,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS v2_projects (
                  id BIGSERIAL PRIMARY KEY,
                  code TEXT UNIQUE,
                  name TEXT NOT NULL,
                  is_active BOOLEAN NOT NULL DEFAULT TRUE,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS v2_time_entries (
                  id BIGSERIAL PRIMARY KEY,
                  person_id BIGINT NOT NULL REFERENCES v2_people(id) ON DELETE CASCADE,
                  project_id BIGINT REFERENCES v2_projects(id) ON DELETE SET NULL,
                  work_date DATE NOT NULL,
                  hours NUMERIC(5,2) NOT NULL CHECK (hours >= 0),
                  notes TEXT,
                  status TEXT NOT NULL DEFAULT 'draft', -- draft|submitted|approved
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS v2_time_entries_person_date
                ON v2_time_entries(person_id, work_date);
            """)
            conn.commit()

            # seed default data if empty
            cur.execute("SELECT COUNT(*) FROM v2_projects;")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO v2_projects(code, name, is_active) VALUES (%s,%s,TRUE);",
                            ("INT", "Internal"))
            cur.execute("SELECT COUNT(*) FROM v2_people;")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO v2_people(name, email) VALUES (%s,%s);",
                            ("Ada Lovelace", "ada@example.com"))
            conn.commit()

# ---------- app + templates ----------
app = FastAPI(title="Time Entry Demo (v2)")
# Paths: app root (this file's folder) and repository root
APP_ROOT = Path(__file__).resolve().parent
REPO_ROOT = APP_ROOT.parent
# Use the templates folder bundled with the app package so templates like
# app/templates/my_week.html are discovered correctly.
TEMPLATES_DIR = APP_ROOT / "templates"
STATIC_DIR = REPO_ROOT / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

ensure_v2_schema()

def render_or_fallback(tpl: str, ctx: dict, fallback_html: str) -> Response:
    try:
        return templates.TemplateResponse(tpl, ctx)
    except TemplateNotFound:
        return HTMLResponse(fallback_html)

def html_error(msg: str, err: Exception) -> HTMLResponse:
    tb = traceback.format_exc()
    body = (
        "<html><body style='font-family:system-ui;max-width:900px;margin:2rem auto'>"
        "<h1>Internal error</h1>"
        f"<p>{msg}</p>"
        "<pre style='white-space:pre-wrap;background:#fafafa;border:1px solid #ddd;padding:1rem;border-radius:8px;'>"
        f"{tb}"
        "</pre></body></html>"
    )
    return HTMLResponse(body, status_code=500)

# ---------- diag route ----------
@app.get("/diag", response_class=HTMLResponse)
async def diag() -> Response:
    try:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT current_schema() AS schema, now() AS now;")
                meta = cur.fetchone()

                def table_info(name: str):
                    cur.execute("""
                        SELECT column_name, data_type, is_nullable
                        FROM information_schema.columns
                        WHERE table_schema=current_schema() AND table_name=%s
                        ORDER BY ordinal_position;
                    """, (name,))
                    cols = cur.fetchall()
                    cur.execute(f"SELECT COUNT(*) AS c FROM {name};")
                    cnt = cur.fetchone()["c"]
                    return cols, cnt

                vp_cols, vp_cnt = table_info("v2_people")
                vpr_cols, vpr_cnt = table_info("v2_projects")
                vt_cols, vt_cnt = table_info("v2_time_entries")

        def render_cols(cols):
            return "".join(
                f"<li><code>{c['column_name']}</code> — {c['data_type']} — nullable: {c['is_nullable']}</li>"
                for c in cols
            )

        html = f"""
        <html><body style="font-family:system-ui;max-width:900px;margin:2rem auto">
          <h1>Diagnostics</h1>
          <p><b>schema:</b> {meta['schema']} &nbsp; <b>now:</b> {meta['now']}</p>

          <h2>v2_people (rows: {vp_cnt})</h2>
          <ul>{render_cols(vp_cols)}</ul>

          <h2>v2_projects (rows: {vpr_cnt})</h2>
          <ul>{render_cols(vpr_cols)}</ul>

          <h2>v2_time_entries (rows: {vt_cnt})</h2>
          <ul>{render_cols(vt_cols)}</ul>
        </body></html>
        """
        return HTMLResponse(html)
    except Exception as e:
        return html_error("While running /diag", e)

# ---------- routes ----------
@app.get("/healthz")
async def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")

@app.get("/")
async def root_redirect() -> RedirectResponse:
    y, w, _ = date.today().isocalendar()
    return RedirectResponse(f"/my-week?year={y}&week={w}", status_code=status.HTTP_302_FOUND)

# My Week — time entry grid
@app.get("/my-week", response_class=HTMLResponse)
async def my_week(request: Request, year: Optional[int] = None, week: Optional[int] = None, person_id: Optional[int] = None) -> Response:
    try:
        today = date.today()
        if not year or not week:
            y, w, _ = today.isocalendar()
            year, week = year or y, week or w

        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT id, name FROM v2_people ORDER BY name;")
                people = cur.fetchall()
            if not person_id:
                person_id = pick_default_person_id(conn)

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT id, code, name FROM v2_projects WHERE is_active IS TRUE ORDER BY name;")
                projects = cur.fetchall()

            days = iso_week_dates(year, week)
            start, end = days[0], days[-1]

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("""
                    SELECT te.id, te.work_date, te.hours, te.notes, te.status,
                           p.id AS project_id, p.name AS project_name, p.code AS project_code
                      FROM v2_time_entries te
                 LEFT JOIN v2_projects p ON p.id = te.project_id
                     WHERE te.person_id = %s AND te.work_date BETWEEN %s AND %s
                  ORDER BY te.work_date, te.id;
                """, (person_id, start, end))
                rows = cur.fetchall()

            by_day: Dict[date, List[dict]] = {d: [] for d in days}
            total = 0.0
            for r in rows:
                by_day[r["work_date"]].append(r)
                total += float(r["hours"] or 0)

            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                      COALESCE(BOOL_AND(status='approved'), FALSE) AS all_approved,
                      COALESCE(BOOL_OR(status='submitted'), FALSE) AS any_submitted
                    FROM v2_time_entries
                    WHERE person_id=%s AND work_date BETWEEN %s AND %s;
                """, (person_id, start, end))
                all_approved, any_submitted = cur.fetchone()

        ctx = {
            "request": request,
            "year": year,
            "week": week,
            "days": days,
            "by_day": by_day,
            "people": people,
            "person_id": person_id,
            "projects": projects,
            "total_hours": total,
            "status_hint": "approved" if all_approved else ("submitted" if any_submitted else "draft"),
        }
        return render_or_fallback("my_week.html", ctx, "<h1>My Week</h1><p>templates/my_week.html missing.</p>")

    except Exception as e:
        return html_error("While rendering /my-week", e)

@app.post("/time/add")
async def time_add(
    person_id: int = Form(...),
    work_date: str = Form(...),
    project_id: Optional[int] = Form(None),
    hours: float = Form(...),
    notes: Optional[str] = Form(None),
    year: int = Form(...),
    week: int = Form(...)
) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO v2_time_entries (person_id, project_id, work_date, hours, notes, status)
                VALUES (%s, %s, %s, %s, %s, 'draft');
            """, (person_id, project_id, work_date, hours, notes))
            conn.commit()
    return RedirectResponse(f"/my-week?year={year}&week={week}&person_id={person_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/time/delete/{entry_id}")
async def time_delete(entry_id: int, person_id: int = Form(...), year: int = Form(...), week: int = Form(...)) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM v2_time_entries WHERE id=%s;", (entry_id,))
            conn.commit()
    return RedirectResponse(f"/my-week?year={year}&week={week}&person_id={person_id}", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/time/submit-week")
async def time_submit_week(person_id: int = Form(...), year: int = Form(...), week: int = Form(...)) -> RedirectResponse:
    start, end = iso_week_dates(year, week)[0], iso_week_dates(year, week)[-1]
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE v2_time_entries
                   SET status='submitted'
                 WHERE person_id=%s AND work_date BETWEEN %s AND %s AND status='draft';
            """, (person_id, start, end))
            conn.commit()
    return RedirectResponse(f"/my-week?year={year}&week={week}&person_id={person_id}", status_code=status.HTTP_303_SEE_OTHER)

# Approvals
@app.get("/approvals", response_class=HTMLResponse)
async def approvals(request: Request) -> Response:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
                SELECT te.id, te.person_id, pe.name AS person_name, te.work_date, te.hours, te.notes, te.status,
                       p.code AS project_code, p.name AS project_name
                  FROM v2_time_entries te
             LEFT JOIN v2_people pe   ON pe.id = te.person_id
             LEFT JOIN v2_projects p  ON p.id = te.project_id
                 WHERE te.status='submitted'
              ORDER BY te.person_id, te.work_date, te.id;
            """)
            rows = cur.fetchall()
    ctx = {"request": request, "rows": rows}
    return render_or_fallback("approvals.html", ctx, "<h1>Approvals</h1><p>templates/approvals.html missing.</p>")

@app.post("/approvals/approve/{entry_id}")
async def approvals_approve(entry_id: int) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE v2_time_entries SET status='approved' WHERE id=%s;", (entry_id,))
            conn.commit()
    return RedirectResponse("/approvals", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/approvals/reject/{entry_id}")
async def approvals_reject(entry_id: int) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE v2_time_entries SET status='draft' WHERE id=%s;", (entry_id,))
            conn.commit()
    return RedirectResponse("/approvals", status_code=status.HTTP_303_SEE_OTHER)

# People
@app.get("/people", response_class=HTMLResponse)
async def people_list(request: Request) -> Response:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, name, email, created_at FROM v2_people ORDER BY name;")
            rows = cur.fetchall()
    ctx = {"request": request, "rows": rows}
    return render_or_fallback("people.html", ctx, "<h1>People</h1><p>templates/people.html missing.</p>")

@app.post("/people/add")
async def people_add(name: str = Form(...), email: Optional[str] = Form(None)) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO v2_people(name, email)
                VALUES (%s, %s)
                ON CONFLICT (email) DO UPDATE SET name=EXCLUDED.name;
            """, (name.strip(), email))
            conn.commit()
    return RedirectResponse("/people", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/people/delete/{person_id}")
async def people_delete(person_id: int) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM v2_people WHERE id=%s;", (person_id,))
            conn.commit()
    return RedirectResponse("/people", status_code=status.HTTP_303_SEE_OTHER)

# Projects
@app.get("/projects", response_class=HTMLResponse)
async def projects_list(request: Request) -> Response:
    with connect() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, code, name, is_active FROM v2_projects ORDER BY is_active DESC, name;")
            rows = cur.fetchall()
    ctx = {"request": request, "rows": rows}
    return render_or_fallback("projects.html", ctx, "<h1>Projects</h1><p>templates/projects.html missing.</p>")

@app.post("/projects/add")
async def projects_add(code: Optional[str] = Form(None), name: str = Form(...)) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO v2_projects(code, name, is_active)
                VALUES (NULLIF(%s,''), %s, TRUE)
                ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, is_active=TRUE;
            """, (code, name.strip()))
            conn.commit()
    return RedirectResponse("/projects", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/projects/toggle/{project_id}")
async def projects_toggle(project_id: int) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE v2_projects SET is_active = NOT is_active WHERE id=%s;", (project_id,))
            conn.commit()
    return RedirectResponse("/projects", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/projects/delete/{project_id}")
async def projects_delete(project_id: int) -> RedirectResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM v2_projects WHERE id=%s;", (project_id,))
            conn.commit()
    return RedirectResponse("/projects", status_code=status.HTTP_303_SEE_OTHER)

# Reset v2 schema only (doesn't touch old tables)
@app.post("/v2/reset")
async def v2_reset() -> PlainTextResponse:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS v2_time_entries CASCADE;")
            cur.execute("DROP TABLE IF EXISTS v2_projects CASCADE;")
            cur.execute("DROP TABLE IF EXISTS v2_people CASCADE;")
            conn.commit()
    ensure_v2_schema()
    return PlainTextResponse("v2 schema reset complete")
