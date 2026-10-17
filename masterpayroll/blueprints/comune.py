"""Strumenti comuni a tutti i blueprint: ambiente dell'allievo, lettura dei moduli, messaggi."""
import re
from datetime import date
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, request, session
from flask_login import current_user

from .. import ensure_workspace, login_manager
from ..models import Message, Workspace, db
from ..payroll import UserError
from ..safe_eval import SafeEvalError, check_code

def area(nome, url_prefix=None):
    """Blueprint di un'attività: cartella propria, templates/<nome>/, utente e ambiente caricati prima di ogni pagina."""
    bp = Blueprint(nome, import_name="masterpayroll.blueprints." + nome, url_prefix=url_prefix, template_folder="templates")
    bp.before_request(_carica_ambiente)
    return bp


def _carica_ambiente():
    if not current_user.is_authenticated:
        return login_manager.unauthorized()
    g.ws_altrui = False
    ws_view = session.get("ws_view")
    if current_user.is_docente and ws_view:
        ws = db.session.get(Workspace, ws_view)
        if ws and ws.owner_id != current_user.id:
            g.ws = ws
            g.ws_altrui = True
            return None
        session.pop("ws_view", None)
    g.ws = ensure_workspace(current_user)
    return None


def author():
    return current_user.display_name if current_user.is_authenticated else ""


def ws_get(model, obj_id):
    obj = db.session.get(model, obj_id) if obj_id else None
    if obj is None or getattr(obj, "workspace_id", None) != g.ws.id:
        abort(404)
    return obj


def ws_query(model):
    return model.query.filter_by(workspace_id=g.ws.id)


def f_str(name, default=""):
    return (request.form.get(name) or default).strip()


def f_text(name):
    return (request.form.get(name) or "").replace("\r\n", "\n")


def parse_float(raw, default=0.0):
    raw = (raw or "").strip().replace(" ", "").replace("€", "")
    if raw == "":
        return default
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", raw):
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return default


def f_float(name, default=0.0):
    return parse_float(request.form.get(name), default)


def f_int(name, default=0):
    return int(parse_float(request.form.get(name), default))


def f_bool(name):
    return request.form.get(name) in ("on", "1", "true", "True")


def f_date(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def f_id(name):
    v = request.form.get(name, type=int)
    return v or None


def code_errors(fields):
    """Controlla il codice delle regole prima di salvarlo: [(etichetta, sorgente, mode)]."""
    errs = []
    for label, src, mode in fields:
        if src is None or not str(src).strip():
            continue
        try:
            check_code(src, mode)
        except SafeEvalError as exc:
            errs.append(f"{label}: {exc}")
    return errs


def handle_user_error(fn):
    """Come Odoo: un UserError annulla l'operazione e mostra il messaggio."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except UserError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(request.referrer or request.path)
    return wrapper


def messages_for(model, res_id):
    return (Message.query.filter_by(workspace_id=g.ws.id, model=model, res_id=res_id)
            .order_by(Message.date.desc(), Message.id.desc()).all())


def post_note(model, res_id):
    body = f_str("body")
    if body:
        db.session.add(Message(workspace_id=g.ws.id, model=model, res_id=res_id, body=body, author=author(),
                               message_type="comment"))
        db.session.commit()


def group_rows(rows, key_fn, label_fn=None):
    """Raggruppa righe (come 'Raggruppa per' di Odoo): [(etichetta, [righe])]."""
    groups = {}
    order = []
    for r in rows:
        k = key_fn(r)
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append(r)
    return [(label_fn(k) if label_fn else k, groups[k]) for k in order]
