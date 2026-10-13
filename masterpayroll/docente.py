import csv
import io
import re
import secrets
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user

from . import ensure_workspace, login_manager
from .models import (Attivita, Esercitazione, EsercitazioneSvolta, Payslip, User, db)

bp = Blueprint("docente", __name__, url_prefix="/docente")

GAP = timedelta(minutes=10)      # oltre 10 minuti senza azioni la sessione si chiude
MIN_EVENTO = timedelta(minutes=2)  # ogni sessione vale almeno 2 minuti


def docente_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_docente:
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


def sessioni_lavoro(timestamps):
    """Raggruppa le azioni in sessioni: tempo reale di lavoro, non pagina aperta."""
    out = []
    start = prev = None
    for ts in sorted(timestamps):
        if start is None:
            start = prev = ts
        elif ts - prev > GAP:
            out.append((start, prev + MIN_EVENTO))
            start = prev = ts
        else:
            prev = ts
    if start is not None:
        out.append((start, prev + MIN_EVENTO))
    return out


def ore_allievo(user_id, da=None, a=None):
    q = db.session.query(Attivita.ts).filter(Attivita.user_id == user_id)
    if da:
        q = q.filter(Attivita.ts >= datetime.combine(da, datetime.min.time()))
    if a:
        q = q.filter(Attivita.ts < datetime.combine(a + timedelta(days=1), datetime.min.time()))
    sess = sessioni_lavoro([t for (t,) in q])
    per_giorno = defaultdict(float)
    for s, e in sess:
        per_giorno[s.date()] += (e - s).total_seconds() / 3600
    return sum(per_giorno.values()), dict(sorted(per_giorno.items())), len(sess)


def _username(nome, cognome):
    base = f"{nome}.{cognome}".lower()
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9.]", "", base).strip(".") or "allievo"
    username, n = base, 2
    while User.query.filter_by(username=username).first():
        username = f"{base}{n}"
        n += 1
    return username


def _password():
    alfabeto = "abcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(8))


def _filtro_periodo():
    def parse(v):
        try:
            return date.fromisoformat(v) if v else None
        except ValueError:
            return None
    return parse(request.args.get("da")), parse(request.args.get("a"))


@bp.route("/", methods=["GET", "POST"])
@docente_required
def index():
    credenziali = []
    if request.method == "POST":
        azione = request.form.get("azione")
        if azione == "crea":
            classe = (request.form.get("classe") or "").strip()
            for riga in (request.form.get("elenco") or "").splitlines():
                parti = riga.replace(";", " ").replace(",", " ").split()
                if len(parti) < 2:
                    continue
                cognome, nome = parti[0].title(), " ".join(parti[1:]).title()
                pwd = _password()
                u = User(username=_username(nome.split()[0], cognome), display_name=f"{cognome} {nome}",
                         role="allievo", classe=classe)
                u.set_password(pwd)
                db.session.add(u)
                db.session.flush()
                credenziali.append((u.display_name, u.username, pwd))
            db.session.commit()
            for u in User.query.filter(User.username.in_([c[1] for c in credenziali])):
                ensure_workspace(u)
            if credenziali:
                flash(f"Creati {len(credenziali)} allievi. Copia ora le password: non saranno più visibili.",
                      "success")
            else:
                flash("Scrivi un allievo per riga: Cognome Nome.", "warning")
        else:
            u = db.session.get(User, request.form.get("user_id", type=int))
            if not u or u.is_docente:
                abort(404)
            if azione == "password":
                pwd = _password()
                u.set_password(pwd)
                db.session.commit()
                credenziali.append((u.display_name, u.username, pwd))
                flash("Nuova password generata.", "success")
            elif azione == "attiva":
                u.active_flag = not u.active_flag
                db.session.commit()
                flash(f"{u.display_name}: account {'attivato' if u.active_flag else 'disattivato'}.", "info")
            elif azione == "reset":
                from .seed import reset_workspace
                reset_workspace(ensure_workspace(u))
                flash(f"Ambiente di {u.display_name} ripristinato.", "success")
            elif azione == "elimina":
                if request.form.get("conferma") != u.username:
                    flash("Per eliminare scrivi lo username dell'allievo nella conferma.", "warning")
                else:
                    if session.get("ws_view") and u.workspace and session["ws_view"] == u.workspace.id:
                        session.pop("ws_view")
                    Attivita.query.filter_by(user_id=u.id).delete()
                    EsercitazioneSvolta.query.filter_by(user_id=u.id).delete()
                    if u.workspace:
                        from .seed import clear_workspace
                        clear_workspace(u.workspace)
                    db.session.delete(u)
                    db.session.commit()
                    flash("Allievo eliminato.", "success")
    da, a = _filtro_periodo()
    allievi = User.query.filter_by(role="allievo").order_by(User.classe, User.display_name).all()
    n_es = Esercitazione.query.filter_by(attiva=True).count()
    righe = []
    for u in allievi:
        ore, _, n_sess = ore_allievo(u.id, da, a)
        ws_id = u.workspace.id if u.workspace else None
        n_ced = Payslip.query.filter_by(workspace_id=ws_id).filter(
            Payslip.state.in_(["verify", "done"])).count() if ws_id else 0
        n_svolte = EsercitazioneSvolta.query.filter_by(user_id=u.id).count()
        righe.append({"u": u, "ore": ore, "sessioni": n_sess, "cedolini": n_ced, "svolte": n_svolte})
    return render_template("docente.html", righe=righe, credenziali=credenziali, n_es=n_es, da=da, a=a)


@bp.route("/allievo/<int:user_id>")
@docente_required
def allievo(user_id):
    u = db.session.get(User, user_id)
    if not u or u.is_docente:
        abort(404)
    da, a = _filtro_periodo()
    ore, per_giorno, n_sess = ore_allievo(u.id, da, a)
    svolte = (db.session.query(EsercitazioneSvolta, Esercitazione)
              .join(Esercitazione, Esercitazione.id == EsercitazioneSvolta.esercitazione_id)
              .filter(EsercitazioneSvolta.user_id == u.id).order_by(Esercitazione.ordine).all())
    ultime = (Attivita.query.filter_by(user_id=u.id).order_by(Attivita.ts.desc()).limit(30).all())
    return render_template("docente_allievo.html", u=u, ore=ore, per_giorno=per_giorno, n_sess=n_sess,
                           svolte=svolte, ultime=ultime, da=da, a=a)


@bp.route("/apri/<int:user_id>", methods=["POST"])
@docente_required
def apri(user_id):
    u = db.session.get(User, user_id)
    if not u or u.is_docente:
        abort(404)
    ws = ensure_workspace(u)
    session["ws_view"] = ws.id
    flash(f"Stai lavorando nell'ambiente di {u.display_name}. Le modifiche sono sue.", "warning")
    return redirect(url_for("main.dashboard"))


@bp.route("/torna", methods=["POST"])
@docente_required
def torna():
    session.pop("ws_view", None)
    return redirect(url_for("docente.index"))


@bp.route("/report.csv")
@docente_required
def report_csv():
    da, a = _filtro_periodo()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Classe", "Allievo", "Username", "Giorno", "Ore di attività", "Esercitazioni consegnate"])
    for u in User.query.filter_by(role="allievo").order_by(User.classe, User.display_name):
        _, per_giorno, _ = ore_allievo(u.id, da, a)
        n_svolte = EsercitazioneSvolta.query.filter_by(user_id=u.id).count()
        if not per_giorno:
            w.writerow([u.classe, u.display_name, u.username, "", "0,00", n_svolte])
        for giorno, ore in per_giorno.items():
            w.writerow([u.classe, u.display_name, u.username, giorno.strftime("%d/%m/%Y"),
                        f"{ore:.2f}".replace(".", ","), n_svolte])
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=masterpayroll_ore_allievi.csv"})


@bp.route("/esercitazioni", methods=["GET", "POST"])
@docente_required
def esercitazioni():
    if request.method == "POST":
        es_id = request.form.get("id", type=int)
        es = db.session.get(Esercitazione, es_id) if es_id else None
        if request.form.get("azione") == "elimina" and es:
            EsercitazioneSvolta.query.filter_by(esercitazione_id=es.id).delete()
            db.session.delete(es)
        else:
            if es is None:
                es = Esercitazione()
                db.session.add(es)
            es.titolo = (request.form.get("titolo") or "").strip() or "Senza titolo"
            es.testo = (request.form.get("testo") or "").strip()
            es.livello = request.form.get("livello", "base")
            es.ordine = request.form.get("ordine", type=int) or 0
            es.attiva = request.form.get("attiva") == "on"
        db.session.commit()
        flash("Esercitazioni aggiornate.", "success")
        return redirect(url_for("docente.esercitazioni"))
    elenco = Esercitazione.query.order_by(Esercitazione.ordine).all()
    consegne = defaultdict(int)
    for s in EsercitazioneSvolta.query:
        consegne[s.esercitazione_id] += 1
    return render_template("docente_esercitazioni.html", elenco=elenco, consegne=consegne)
