"""ArayFlow Dashboard v0.7.1 - painel web LOCAL para acompanhar calendario e automacao.

Nao publica na Meta, nao remove arquivos R2 e nao altera o Google Sheets.
Apenas a pausa/retomada explicita da tarefa Windows realiza uma modificacao.
"""
from __future__ import annotations

import hmac
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, send_file, session, url_for

from google_client import BASE_DIR, authenticate, read_calendar, services
from r2_storage import R2Storage
from scheduled_publish import APPROVED, decision, scheduled_time

load_dotenv(BASE_DIR / ".env")
ZONE = ZoneInfo("America/Sao_Paulo")
POST_ID = re.compile(r"ARAY-\d{8}-\d{3,}$")
SLIDE_NAME = re.compile(r"ARAY-\d{8}-\d{3,}_slide-(\d+)\.(png|jpg|jpeg)$", re.I)
TASK_NAME = "ArayFlow Publisher"
CACHE_SECONDS = 45


def parse_day(value: str | None) -> str:
    if not value:
        return datetime.now(ZONE).date().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Data invalida: use AAAA-MM-DD")
    return datetime.strptime(value, "%Y-%m-%d").date().isoformat()


def slides_for(root: Path, post_id: str) -> list[Path]:
    if not POST_ID.fullmatch(post_id):
        return []
    day = datetime.strptime(post_id[5:13], "%Y%m%d").date().isoformat()
    folder = root / "downloads" / day / post_id
    if not folder.is_dir():
        return []
    slides = []
    for item in folder.iterdir():
        match = SLIDE_NAME.fullmatch(item.name)
        if (item.is_file() and match and item.name.startswith(post_id + "_slide-")
                and 1 <= int(match[1]) <= 10):
            slides.append((int(match[1]), item))
    return [path for _, path in sorted(slides)]


def snapshot(root: Path):
    """Le SQLite em modo read-only. Nao cria nem altera bancos existentes."""
    data = {"publications": {}, "suite": {}, "sessions": [], "events": [], "asset_count": 0}
    database = root / "data" / "arayflow.sqlite3"
    if not database.is_file():
        return data
    con = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        con.row_factory = sqlite3.Row
        for table, query, key in [
            ("publications", "SELECT post_id,status,media_id,container_id,updated_at FROM publications", "publications"),
            ("business_suite_schedule", "SELECT post_id,target_at,status,note,updated_at FROM business_suite_schedule", "suite"),
            ("daily_syncs", "SELECT day,status,updated_at,last_error FROM daily_syncs ORDER BY updated_at DESC LIMIT 8", "sessions"),
            ("r2_events", "SELECT day,action,object_key,created_at FROM r2_events ORDER BY id DESC LIMIT 12", "events"),
            ("r2_assets", "SELECT COUNT(*) AS total FROM r2_assets", "asset_count"),
        ]:
            exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
            rows = [dict(row) for row in con.execute(query).fetchall()]
            if key in {"publications", "suite"}:
                data[key] = {row["post_id"]: row for row in rows}
            elif key == "asset_count":
                data[key] = rows[0]["total"] if rows else 0
            else:
                data[key] = rows
    finally:
        con.close()
    return data


def task_state() -> str:
    if sys.platform != "win32":
        return "Indisponivel fora do Windows"
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-ScheduledTask -TaskName 'ArayFlow Publisher' -ErrorAction Stop).State.ToString()"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        if proc.returncode:
            return "Nao encontrada"
        state = proc.stdout.strip().splitlines()
        return state[-1].strip() if state else "Indisponivel"
    except (OSError, subprocess.TimeoutExpired):
        return "Indisponivel"


def change_task(action: str) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Controle do agendador disponivel somente no Windows")
    command = {"pause": "Disable-ScheduledTask", "resume": "Enable-ScheduledTask"}.get(action)
    if not command:
        raise ValueError("Acao invalida")
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         f"{command} -TaskName 'ArayFlow Publisher' -ErrorAction Stop | Out-Null"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if proc.returncode:
        raise RuntimeError("O Windows recusou a operacao. Verifique permissao e tarefa instalada.")


def safe_log_lines(root: Path) -> list[str]:
    filename = root / "logs" / "scheduled_publish.log"
    if not filename.is_file():
        return []
    try:
        with filename.open("r", encoding="utf-8", errors="replace") as handle:
            lines = list(deque(handle, maxlen=24))
    except OSError:
        return []
    credentials = [os.getenv(key, "") for key in (
        "TOKEN", "R2_SECRET_ACCESS_KEY", "R2_ACCESS_KEY_ID",
        "APP_INSTA_ID", "KEY_SECRET_INSTA"
    ) if len(os.getenv(key, "")) >= 8]
    cleaned = []
    for line in lines:
        for value in credentials:
            line = line.replace(value, "[REDACTED]")
        cleaned.append(line.rstrip()[:380])
    return cleaned


def get_calendar():
    credentials = authenticate()
    sheets, _ = services(credentials)
    return read_calendar(
        sheets,
        os.getenv("GOOGLE_SPREADSHEET_ID", "1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM"),
        os.getenv("GOOGLE_SHEET_NAME", "Calendário"),
    )


def create_app(root: Path | None = None) -> Flask:
    root = Path(root or BASE_DIR).resolve()
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"),
                static_folder=str(Path(__file__).parent / "static"))
    app.config["TRUSTED_HOSTS"] = ["127.0.0.1", "localhost"]
    app.config["MAX_CONTENT_LENGTH"] = 32_768
    keyfile = root / "data" / "dashboard_secret.key"
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        with keyfile.open("x", encoding="ascii") as stream:
            stream.write(secrets.token_hex(48))
    except FileExistsError:
        pass
    app.secret_key = keyfile.read_text(encoding="ascii").strip()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
    cache_lock = Lock()
    cache = {"at": 0., "rows": None}

    def cached_rows(force=False):
        with cache_lock:
            if not force and cache["rows"] is not None and time.monotonic() - cache["at"] < CACHE_SECONDS:
                return cache["rows"]
            rows = get_calendar()
            cache.update(at=time.monotonic(), rows=rows)
            return rows

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def dashboard():
        try:
            day = parse_day(request.args.get("date"))
        except ValueError:
            abort(400)
        force = request.args.get("refresh") == "1"
        google_error = None
        try:
            rows = cached_rows(force)
        except Exception:
            app.logger.exception("Falha ao carregar Google Sheets")
            rows, google_error = [], "Google Sheets indisponivel. Consulte o terminal para detalhes."
        db = snapshot(root)
        posts = []
        now = datetime.now(ZONE)
        selected_date = datetime.strptime(day, "%Y-%m-%d").date()
        for row in rows:
            if row.get("Data", "").strip() != selected_date.strftime("%d/%m/%Y"):
                continue
            post_id = row.get("ID", "").strip()
            if not POST_ID.fullmatch(post_id):
                continue
            status = db["publications"].get(post_id, {})
            suite = db["suite"].get(post_id, {})
            images = slides_for(root, post_id)
            try:
                stage = decision(row, now)
            except (ValueError, KeyError):
                stage = "INVALIDO"
            posts.append({
                "id": post_id, "time": row.get("Horário", ""), "kind": row.get("Tipo", ""),
                "status": row.get("Status", ""), "approved": row.get("Status", "").strip().casefold() in APPROVED,
                "caption": row.get("Legenda pronta", ""), "expected": row.get("Qtd. imagens", ""),
                "local_count": len(images), "has_cover": bool(images),
                "stage": stage, "publication_status": status.get("status", "not_started"),
                "suite_status": suite.get("status", "not_started"),
                "suite_target": suite.get("target_at"),
                "media_id": status.get("media_id"), "container_id": status.get("container_id"),
                "updated_at": status.get("updated_at"),
                "drive_link": row.get("Pasta das imagens", ""),
            })
        posts.sort(key=lambda p: p["time"].zfill(5))
        selected_id = request.args.get("post", "")
        selected_post = next((p for p in posts if p["id"] == selected_id), None)
        slides = list(range(1, len(slides_for(root, selected_id)) + 1)) if selected_post else []
        count_remote, r2_error = None, None
        if request.args.get("r2") == "1":
            try:
                count_remote = len(R2Storage().list_managed())
            except Exception:
                app.logger.exception("Falha ao consultar R2")
                r2_error = "Falha ao consultar R2. Verifique credenciais/conexao."
        csrf = session.setdefault("csrf", secrets.token_urlsafe(32))
        previous_day = (selected_date - timedelta(days=1)).isoformat()
        next_day = (selected_date + timedelta(days=1)).isoformat()
        return render_template(
            "dashboard.html", day=day, today=datetime.now(ZONE).date().isoformat(),
            previous_day=previous_day, next_day=next_day, posts=posts, selected_post=selected_post,
            slides=slides, db=db, logs=safe_log_lines(root), csrf=csrf, google_error=google_error,
            task_state=task_state(), autopublish=os.getenv("ARAYFLOW_AUTOPUBLISH_ENABLED", "").lower() == "true",
            remote_count=count_remote, r2_error=r2_error,
            approved=sum(p["approved"] for p in posts),
            published=sum(p["publication_status"] == "published" for p in posts),
            prepared=sum(p["publication_status"] == "prepared" for p in posts),
            suite_scheduled=sum(p["suite_status"] == "scheduled" for p in posts),
            suite_pending=sum(p["suite_status"] in ("awaiting_confirmation", "needs_review") for p in posts),
            failures=sum(p["publication_status"] in ("uncertain", "failed", "preparing") for p in posts),
            spreadsheet_url="https://docs.google.com/spreadsheets/d/" +
                os.getenv("GOOGLE_SPREADSHEET_ID", "1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM") + "/edit",
        )

    @app.get("/media/<post_id>/<int:slide>")
    def media(post_id, slide):
        if not POST_ID.fullmatch(post_id) or not 1 <= slide <= 10:
            abort(404)
        files = slides_for(root, post_id)
        if slide > len(files):
            abort(404)
        path = files[slide - 1]
        if path.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            abort(404)
        return send_file(path, mimetype="image/png" if path.suffix.lower() == ".png" else "image/jpeg",
                         conditional=True, max_age=60)

    @app.post("/business-suite/start")
    def start_business_suite():
        expected = session.get("csrf", "")
        received = request.form.get("csrf", "")
        if not expected or not received or not hmac.compare_digest(received, expected):
            abort(403)
        origin = request.headers.get("Origin")
        if origin and origin not in {"http://127.0.0.1:8766", "http://localhost:8766"}:
            abort(403)
        if request.form.get("confirmation", "") != "ABRIR":
            abort(400)
        try:
            day = parse_day(request.form.get("date"))
        except ValueError:
            abort(400)
        if sys.platform != "win32":
            flash("Abertura direta disponivel somente no Windows; use o comando do painel.", "error")
            return redirect(url_for("dashboard", date=day))
        if os.getenv("ARAYFLOW_AUTOPUBLISH_ENABLED", "").strip().lower() == "true":
            flash("Desative ARAYFLOW_AUTOPUBLISH_ENABLED no .env e reinicie o Flask antes de abrir.", "error")
            return redirect(url_for("dashboard", date=day))
        if task_state() in {"Ready", "Running", "Queued"}:
            flash("Pause primeiro a tarefa ArayFlow Publisher para evitar duplicatas.", "error")
            return redirect(url_for("dashboard", date=day))
        py = root / ".venv" / "Scripts" / "python.exe"
        worker = root / "business_suite_assistant.py"
        if not py.is_file() or not worker.is_file():
            flash("Python .venv ou assistente nao encontrado na pasta do projeto.", "error")
            return redirect(url_for("dashboard", date=day))
        try:
            subprocess.Popen(
                [str(py), str(worker), "--date", day, "--start"],
                cwd=str(root), creationflags=subprocess.CREATE_NEW_CONSOLE,
                stdin=None, stdout=None, stderr=None,
            )
            flash("Assistente iniciado em nova janela. Confirme os agendamentos nela.", "success")
        except OSError:
            app.logger.exception("Nao foi possivel iniciar assistente local")
            flash("Falha ao abrir o assistente no Windows.", "error")
        return redirect(url_for("dashboard", date=day))

    @app.post("/scheduler/<action>")
    def scheduler_action(action):
        if action not in {"pause", "resume"}:
            abort(404)
        expected = session.get("csrf", "")
        received = request.form.get("csrf", "")
        if not expected or not received or not hmac.compare_digest(received, expected):
            abort(403)
        origin = request.headers.get("Origin")
        if origin and origin not in {"http://127.0.0.1:8766", "http://localhost:8766"}:
            abort(403)
        if request.form.get("confirmation") != ("PAUSAR" if action == "pause" else "RETOMAR"):
            flash("Confirmacao invalida; nenhuma alteracao realizada.", "error")
        else:
            try:
                change_task(action)
                flash("Tarefa pausada." if action == "pause" else "Tarefa retomada.", "success")
            except RuntimeError as exc:
                app.logger.warning("Falha de controle da tarefa: %s", exc)
                flash(str(exc), "error")
        return redirect(url_for("dashboard"))

    return app


if __name__ == "__main__":
    import webbrowser
    import threading
    app = create_app()
    print("ArayFlow Dashboard: http://127.0.0.1:8766 (somente computador local)")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:8766")).start()
    app.run(host="127.0.0.1", port=8766, debug=False, use_reloader=False, threaded=True)
