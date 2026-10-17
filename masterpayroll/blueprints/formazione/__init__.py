"""Blueprint «formazione» — corsi di formazione e partecipanti (modulo OCA hr_course).

Una cartella per attività: le pagine HTML sono in templates/formazione/."""
from collections import defaultdict
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for

from ... import payroll
from ...models import Corso, CorsoPartecipante, Employee, db
from ...scadenze import CATEGORIE_CORSO, ESITI_CORSO, STATI_CORSO
from ..comune import area, author, f_date, f_float, f_id, f_int, f_str, f_text, handle_user_error, ws_get, ws_query

bp = area("formazione")


def _salva(c):
    c.titolo = f_str("titolo")
    if not c.titolo:
        raise payroll.UserError("Il titolo del corso è obbligatorio.")
    c.categoria, c.ente = f_str("categoria", "tecnico"), f_str("ente")
    c.data_inizio, c.data_fine = f_date("data_inizio"), f_date("data_fine") or f_date("data_inizio")
    if c.data_inizio and c.data_fine and c.data_fine < c.data_inizio:
        raise payroll.UserError("La data di fine deve essere uguale o successiva all'inizio.")
    c.ore, c.costo, c.validita_anni = f_float("ore"), f_float("costo"), f_int("validita_anni")
    c.stato, c.note = f_str("stato", "programmato"), f_text("note")


@bp.route("/formazione", methods=["GET", "POST"])
@handle_user_error
def corsi():
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        c = Corso(workspace_id=g.ws.id)
        _salva(c)
        db.session.add(c)
        db.session.commit()
        flash("Corso creato: aggiungi i partecipanti.", "success")
        return redirect(url_for("formazione.corso", corso_id=c.id))
    righe = ws_query(Corso).order_by(Corso.data_inizio.desc()).all()
    anni = defaultdict(lambda: {"corsi": 0, "ore": 0.0, "costo": 0.0, "ore_persona": 0.0})
    for c in righe:
        if c.stato == "annullato" or not c.data_inizio:
            continue
        a = anni[c.data_inizio.year]
        a["corsi"] += 1
        a["ore"] += c.ore or 0
        a["costo"] += c.costo or 0
        a["ore_persona"] += (c.ore or 0) * len(c.partecipanti)
    return render_template("formazione/corsi.html", righe=righe, categorie=CATEGORIE_CORSO, stati=STATI_CORSO,
                           anni=sorted(anni.items(), reverse=True))


@bp.route("/formazione/<int:corso_id>", methods=["GET", "POST"])
@handle_user_error
def corso(corso_id):
    c = ws_get(Corso, corso_id)
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        action = request.form.get("action", "save")
        if action == "delete":
            db.session.delete(c)
            db.session.commit()
            flash("Corso eliminato.", "success")
            return redirect(url_for("formazione.corsi"))
        if action == "add":
            e = ws_get(Employee, f_id("employee_id"))
            if any(p.employee_id == e.id for p in c.partecipanti):
                raise payroll.UserError(f"{e.name} è già iscritto.")
            c.partecipanti.append(CorsoPartecipante(workspace_id=g.ws.id, employee=e, esito=f_str("esito", "iscritto")))
            payroll.log_message(g.ws.id, "hr.employee", e.id, author=author(), body=f"Iscritto al corso «{c.titolo}».")
        elif action.startswith("del_"):
            p = ws_get(CorsoPartecipante, int(action[4:]))
            db.session.delete(p)
        else:
            _salva(c)
            for p in c.partecipanti:
                esito = request.form.get(f"esito_{p.id}")
                if esito:
                    p.esito = esito
        db.session.commit()
        flash("Corso salvato.", "success")
        return redirect(url_for("formazione.corso", corso_id=c.id))
    iscritti = {p.employee_id for p in c.partecipanti}
    return render_template("formazione/corso.html", c=c, categorie=CATEGORIE_CORSO, stati=STATI_CORSO, esiti=ESITI_CORSO,
                           liberi=[e for e in ws_query(Employee).filter_by(active=True).order_by(Employee.last_name)
                                   if e.id not in iscritti])


@bp.route("/formazione/dipendenti")
def per_dipendente():
    """Matrice della formazione: per ogni dipendente in forza i corsi superati, le ore e la scadenza."""
    emps = ws_query(Employee).filter_by(active=True).order_by(Employee.last_name).all()
    per = {e.id: [] for e in emps}
    for p in CorsoPartecipante.query.join(Corso).filter(Corso.workspace_id == g.ws.id):
        if p.employee_id in per:
            per[p.employee_id].append(p)
    for v in per.values():
        v.sort(key=lambda p: p.corso.data_inizio or p.corso.data_fine or date.min, reverse=True)
    return render_template("formazione/per_dipendente.html", emps=emps, per=per, categorie=dict(CATEGORIE_CORSO),
                           esiti=dict(ESITI_CORSO))
