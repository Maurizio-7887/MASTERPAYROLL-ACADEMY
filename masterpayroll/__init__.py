"""MasterPayroll Academy - gestionale paghe didattico."""
import hashlib
import os
import secrets

from flask import Flask, abort, g, request, session
from flask_login import LoginManager, current_user
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .models import now, Attivita, User, Workspace, db

login_manager = LoginManager()
login_manager.login_view = "accesso.login"
login_manager.login_message = "Accedi per continuare."

MESI = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio",
        "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]


@event.listens_for(Engine, "connect")
def _sqlite_fk(dbapi_connection, connection_record):
    """SQLite: attiva le foreign key (ON DELETE CASCADE), come in PostgreSQL."""
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def _db_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///masterpayroll.db")
    # Railway fornisce postgres:// o postgresql://: si usa esplicitamente il driver psycopg2
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg2://" + url[len(prefix):]
    return url


def _fallback_secret():
    """Senza SECRET_KEY tutti i worker devono comunque condividere la stessa chiave."""
    return hashlib.sha256(("masterpayroll-" + _db_url()).encode()).hexdigest()


def euro(value, decimals=2):
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return value
    s = f"{v:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def num(value, decimals=2):
    """Numero all'italiana: niente decimali inutili (8 -> "8", 12,7168 -> "12,7168")."""
    if value is None or value == "":
        return ""
    v = round(float(value), decimals)
    if v == int(v):
        return euro(v, 0)
    s = euro(v, decimals)
    if "," in s:
        intero, dec = s.split(",")
        dec = dec.rstrip("0")
        if len(dec) < 2 and decimals >= 2:
            dec = dec.ljust(2, "0")
        s = f"{intero},{dec}" if dec else intero
    return s


def inval(value):
    """Valore per i campi di input: virgola decimale, senza separatore delle migliaia."""
    if value is None or value == "":
        return ""
    v = float(value)
    if v == int(v):
        return str(int(v))
    return f"{v:.4f}".rstrip("0").replace(".", ",")


def data(d, fmt="%d/%m/%Y"):
    return d.strftime(fmt) if d else ""


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or _fallback_secret(),
        SQLALCHEMY_DATABASE_URI=_db_url(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,  # documenti dei dipendenti: file fino a 5 MB
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "docente"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD", ""),
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    login_manager.init_app(app)

    app.jinja_env.filters["euro"] = euro
    app.jinja_env.filters["num"] = num
    app.jinja_env.filters["inval"] = inval
    app.jinja_env.filters["data"] = data
    import json as _json
    app.jinja_env.filters["fromjson"] = lambda s: _json.loads(s or "{}")
    app.jinja_env.globals["MESI"] = MESI
    from .models import CONTRACT_STATES, PAYSLIP_STATES, SCHEDULE_PAY
    app.jinja_env.globals.update(PAYSLIP_STATES=dict(PAYSLIP_STATES), CONTRACT_STATES=dict(CONTRACT_STATES),
                                 SCHEDULE_PAY=dict(SCHEDULE_PAY))

    # una cartella per attività: masterpayroll/blueprints/<attività>/ con templates/<attività>/*.html
    import importlib
    from .blueprints import AREE
    for nome in AREE:
        app.register_blueprint(importlib.import_module(f".blueprints.{nome}", __name__).bp)

    @app.before_request
    def _csrf_and_tracking():
        if "_csrf" not in session:
            session["_csrf"] = secrets.token_hex(16)
        if request.method == "POST" and not app.config.get("TESTING_NO_CSRF"):
            token = request.form.get("_csrf") or request.headers.get("X-CSRF-Token")
            if not token or token != session.get("_csrf"):
                abort(400, "Sessione scaduta: ricarica la pagina e riprova.")
        if current_user.is_authenticated and request.endpoint and request.endpoint != "static":
            n = now()
            if not current_user.is_docente:
                db.session.add(Attivita(user_id=current_user.id, ts=n, metodo=request.method,
                                        path=request.path[:255]))
            current_user.last_seen = n
            db.session.commit()

    @app.context_processor
    def _inject():
        return {"csrf_token": session.get("_csrf", ""), "ws": getattr(g, "ws", None),
                "ws_altrui": getattr(g, "ws_altrui", False)}

    with app.app_context():
        db.create_all()
        _ensure_admin(app)
        from .seed import seed_esercitazioni
        seed_esercitazioni()

    return app


def _ensure_admin(app):
    username = app.config["ADMIN_USERNAME"]
    user = User.query.filter_by(username=username).first()
    if user:
        if app.config["ADMIN_PASSWORD"] and not user.check_password(app.config["ADMIN_PASSWORD"]):
            user.set_password(app.config["ADMIN_PASSWORD"])  # la variabile d'ambiente comanda
            db.session.commit()
        return
    pwd = app.config["ADMIN_PASSWORD"]
    if not pwd:
        pwd = secrets.token_urlsafe(9)
        app.logger.warning("ADMIN_PASSWORD non impostata: password docente generata = %s", pwd)
        print(f"[MasterPayroll] Utente docente '{username}' creato con password: {pwd}", flush=True)
    user = User(username=username, display_name="Docente", role="docente")
    user.set_password(pwd)
    db.session.add(user)
    db.session.commit()


@login_manager.user_loader
def _load_user(user_id):
    return db.session.get(User, int(user_id))


def ensure_workspace(user):
    """Crea e popola l'ambiente dell'utente al primo accesso."""
    from .models import Parametro
    from .seed import seed_workspace
    ws = user.workspace
    if ws is None:
        ws = Workspace(owner=user)
        db.session.add(ws)
        db.session.commit()
    if not Parametro.query.filter_by(workspace_id=ws.id).first():
        seed_workspace(ws)
    elif not Parametro.query.filter_by(workspace_id=ws.id, codice="SCADENZE_PREAVVISO_GG").first():
        from .seed import upgrade_workspace
        upgrade_workspace(ws)  # ambiente creato con una versione precedente: si aggiunge ciò che manca
    return ws
