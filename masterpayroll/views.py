import re
from collections import OrderedDict, defaultdict
from datetime import date

from flask import (Blueprint, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user

from . import MESI, ensure_workspace, login_manager
from .engine import calcola
from .fiscale import HELPER_DOCS
from .models import (now, INPUT_CATALOGO, INPUT_CODES, Categoria, Cedolino, CedolinoInput,
                     Contratto, Dipendente, Elaborazione, Esercitazione,
                     EsercitazioneSvolta, Livello, Parametro, Regola, ScaglioneIrpef,
                     Struttura, Workspace, db)
from .safe_eval import FormulaError, compile_formula

bp = Blueprint("main", __name__)

INPUT_LABEL = {c: (lbl, um) for c, lbl, um in INPUT_CATALOGO}
INPUT_GRIGLIA = {
    "ordinaria": ["STR25", "STR50", "ORE_ASS", "FERIE", "ROL", "PREMIO", "RIMBORSI", "ANTICIPO"],
    "tredicesima": ["MESI_13"],
}


# ---------------------------------------------------------------------------
# Ambiente corrente e utilità
# ---------------------------------------------------------------------------
@bp.before_request
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


def ws_get(model, obj_id):
    obj = db.session.get(model, obj_id)
    if obj is None or obj.workspace_id != g.ws.id:
        abort(404)
    return obj


def f_float(name, default=0.0):
    raw = (request.form.get(name) or "").strip().replace(" ", "")
    if raw == "":
        return default
    if "," in raw:  # formato italiano 1.234,56
        raw = raw.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", raw):  # 1.500 = millecinquecento
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return default


def f_date(name):
    raw = (request.form.get(name) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def f_str(name, default=""):
    return (request.form.get(name) or default).strip()


def strutture_ws():
    return Struttura.query.filter_by(workspace_id=g.ws.id).order_by(Struttura.tipo_cedolino, Struttura.codice).all()


def livelli_ws():
    return Livello.query.filter_by(workspace_id=g.ws.id).order_by(Livello.codice).all()


def valida_formule(campi):
    errori = []
    for etichetta, src in campi:
        try:
            compile_formula(src)
        except FormulaError as exc:
            errori.append(f"{etichetta}: {exc}")
    return errori


# ---------------------------------------------------------------------------
# Dashboard e guida
# ---------------------------------------------------------------------------
@bp.route("/")
def dashboard():
    ws_id = g.ws.id
    n_dip = Dipendente.query.filter_by(workspace_id=ws_id, attivo=True).count()
    elaborazioni = (Elaborazione.query.filter_by(workspace_id=ws_id)
                    .order_by(Elaborazione.anno.desc(), Elaborazione.mese.desc(), Elaborazione.id.desc())
                    .limit(6).all())
    ultima = elaborazioni[0] if elaborazioni else None
    totali = None
    if ultima:
        ceds = [c for c in ultima.cedolini if c.stato in ("calcolato", "confermato")]
        totali = {"n": len(ceds), "lordo": sum(c.lordo for c in ceds),
                  "netto": sum(c.netto for c in ceds), "costo": sum(c.costo for c in ceds)}
    esercitazioni = Esercitazione.query.filter_by(attiva=True).order_by(Esercitazione.ordine).all()
    svolte = {s.esercitazione_id for s in EsercitazioneSvolta.query.filter_by(user_id=g.ws.owner_id)}
    return render_template("dashboard.html", n_dip=n_dip, elaborazioni=elaborazioni, ultima=ultima,
                           totali=totali, esercitazioni=esercitazioni, svolte=svolte)


@bp.route("/guida")
def guida():
    cats = Categoria.query.filter_by(workspace_id=g.ws.id).order_by(Categoria.sequenza).all()
    params = Parametro.query.filter_by(workspace_id=g.ws.id).order_by(Parametro.id).all()
    return render_template("guida.html", helpers=HELPER_DOCS, cats=cats, params=params,
                           inputs=INPUT_CATALOGO)


@bp.route("/ambiente/reset", methods=["POST"])
def reset_ambiente():
    from .seed import reset_workspace
    if g.ws_altrui:
        abort(403)
    if request.form.get("conferma") != "RIPRISTINA":
        flash("Per ripristinare scrivi RIPRISTINA nella casella di conferma.", "warning")
        return redirect(url_for("main.dashboard"))
    reset_workspace(g.ws)
    flash("Ambiente ripristinato ai dati iniziali di Ferro & Transenne Srl.", "success")
    return redirect(url_for("main.dashboard"))


# ---------------------------------------------------------------------------
# Esercitazioni
# ---------------------------------------------------------------------------
@bp.route("/esercitazioni", methods=["GET", "POST"])
def esercitazioni():
    uid = g.ws.owner_id
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        es_id = int(request.form.get("esercitazione_id", 0))
        rec = EsercitazioneSvolta.query.filter_by(user_id=uid, esercitazione_id=es_id).first()
        if request.form.get("azione") == "annulla":
            if rec:
                db.session.delete(rec)
        else:
            if not rec:
                rec = EsercitazioneSvolta(user_id=uid, esercitazione_id=es_id)
                db.session.add(rec)
            rec.nota = f_str("nota")
            rec.consegnata_at = now()
        db.session.commit()
        flash("Esercitazione aggiornata.", "success")
        return redirect(url_for("main.esercitazioni"))
    elenco = Esercitazione.query.filter_by(attiva=True).order_by(Esercitazione.ordine).all()
    svolte = {s.esercitazione_id: s for s in EsercitazioneSvolta.query.filter_by(user_id=uid)}
    return render_template("esercitazioni.html", elenco=elenco, svolte=svolte)


# ---------------------------------------------------------------------------
# Dipendenti e contratti
# ---------------------------------------------------------------------------
@bp.route("/dipendenti")
def dipendenti():
    mostra = request.args.get("mostra", "attivi")
    q = Dipendente.query.filter_by(workspace_id=g.ws.id)
    if mostra == "attivi":
        q = q.filter_by(attivo=True)
    elenco = q.order_by(Dipendente.matricola).all()
    return render_template("dipendenti.html", elenco=elenco, mostra=mostra)


def _salva_dipendente(d):
    d.matricola = f_str("matricola") or d.matricola
    d.cognome = f_str("cognome")
    d.nome = f_str("nome")
    d.codice_fiscale = f_str("codice_fiscale").upper()
    d.data_nascita = f_date("data_nascita")
    d.comune_residenza = f_str("comune_residenza")
    d.data_assunzione = f_date("data_assunzione")
    d.data_cessazione = f_date("data_cessazione")
    d.qualifica = f_str("qualifica", "operaio")
    d.mansione = f_str("mansione")
    d.reparto = f_str("reparto")
    d.attivo = request.form.get("attivo") == "on"


def _salva_contratto(c):
    c.tipo = f_str("tipo", "indeterminato")
    liv_id = request.form.get("livello_id", type=int)
    c.livello = db.session.get(Livello, liv_id) if liv_id else None
    if c.livello and c.livello.workspace_id != g.ws.id:
        abort(400)
    st_id = request.form.get("struttura_id", type=int)
    c.struttura = db.session.get(Struttura, st_id) if st_id else None
    if c.struttura and c.struttura.workspace_id != g.ws.id:
        abort(400)
    if request.form.get("usa_tabella") == "on" and c.livello:
        c.minimo = c.livello.minimo
        c.scatto_importo = c.livello.scatto_importo
    else:
        c.minimo = f_float("minimo")
        c.scatto_importo = f_float("scatto_importo")
    c.superminimo = f_float("superminimo")
    c.scatti_n = int(f_float("scatti_n"))
    c.part_time = f_float("part_time", 100.0)
    c.ore_settimanali = f_float("ore_settimanali", 40.0)
    c.divisore_orario = f_float("divisore_orario", 173.0) or 173.0
    c.add_reg_rata = f_float("add_reg_rata")
    c.add_com_rata = f_float("add_com_rata")
    c.data_inizio = f_date("data_inizio") or date.today()
    c.data_fine = f_date("data_fine")
    c.attivo = request.form.get("contratto_attivo", "on") == "on"


@bp.route("/dipendenti/nuovo", methods=["GET", "POST"])
def dipendente_nuovo():
    if request.method == "POST":
        if not f_str("cognome") or not f_str("nome") or not f_str("matricola"):
            flash("Matricola, cognome e nome sono obbligatori.", "danger")
        elif Dipendente.query.filter_by(workspace_id=g.ws.id, matricola=f_str("matricola")).first():
            flash("Esiste già un dipendente con questa matricola.", "danger")
        else:
            d = Dipendente(workspace_id=g.ws.id)
            _salva_dipendente(d)
            c = Contratto(workspace_id=g.ws.id)
            _salva_contratto(c)
            d.contratti.append(c)
            db.session.add(d)
            db.session.commit()
            flash(f"Dipendente {d.nominativo} creato.", "success")
            return redirect(url_for("main.dipendente", dip_id=d.id))
    prossima = 1 + max([int(d.matricola) for d in Dipendente.query.filter_by(workspace_id=g.ws.id)
                        if d.matricola.isdigit()] or [0])
    ordinaria = next((s for s in strutture_ws() if s.tipo_cedolino == "ordinaria"), None)
    return render_template("dipendente_form.html", d=None, c=None, nuova_matricola=f"{prossima:04d}",
                           livelli=livelli_ws(), strutture=strutture_ws(), struttura_default=ordinaria)


@bp.route("/dipendenti/<int:dip_id>")
def dipendente(dip_id):
    d = ws_get(Dipendente, dip_id)
    cedolini = (Cedolino.query.filter_by(workspace_id=g.ws.id, dipendente_id=d.id)
                .order_by(Cedolino.anno.desc(), Cedolino.mese.desc(), Cedolino.id.desc()).all())
    return render_template("dipendente.html", d=d, cedolini=cedolini)


@bp.route("/dipendenti/<int:dip_id>/modifica", methods=["GET", "POST"])
def dipendente_modifica(dip_id):
    d = ws_get(Dipendente, dip_id)
    if request.method == "POST":
        _salva_dipendente(d)
        db.session.commit()
        flash("Anagrafica aggiornata.", "success")
        return redirect(url_for("main.dipendente", dip_id=d.id))
    return render_template("dipendente_form.html", d=d, c=None, livelli=livelli_ws(),
                           strutture=strutture_ws(), struttura_default=None, nuova_matricola=d.matricola)


@bp.route("/dipendenti/<int:dip_id>/elimina", methods=["POST"])
def dipendente_elimina(dip_id):
    d = ws_get(Dipendente, dip_id)
    if Cedolino.query.filter_by(dipendente_id=d.id, stato="confermato").first():
        flash("Ha cedolini confermati: non si può eliminare. Imposta invece la data di cessazione "
              "e togli la spunta 'attivo'.", "warning")
        return redirect(url_for("main.dipendente", dip_id=d.id))
    for ced in Cedolino.query.filter_by(dipendente_id=d.id).all():
        db.session.delete(ced)
    db.session.delete(d)
    db.session.commit()
    flash("Dipendente eliminato.", "success")
    return redirect(url_for("main.dipendenti"))


@bp.route("/dipendenti/<int:dip_id>/contratto/nuovo", methods=["GET", "POST"])
@bp.route("/contratti/<int:con_id>/modifica", methods=["GET", "POST"])
def contratto_form(dip_id=None, con_id=None):
    if con_id:
        c = ws_get(Contratto, con_id)
        d = c.dipendente
    else:
        d = ws_get(Dipendente, dip_id)
        c = None
    if request.method == "POST":
        nuovo = c is None
        if nuovo:
            c = Contratto(workspace_id=g.ws.id)
        _salva_contratto(c)
        if nuovo:
            if c.attivo:
                for old in d.contratti:
                    old.attivo = False
            d.contratti.append(c)
        db.session.commit()
        flash("Contratto salvato. I cedolini già calcolati vanno ricalcolati per vedere l'effetto.", "success")
        return redirect(url_for("main.dipendente", dip_id=d.id))
    return render_template("contratto_form.html", d=d, c=c, livelli=livelli_ws(), strutture=strutture_ws())


# ---------------------------------------------------------------------------
# Elaborazioni mensili
# ---------------------------------------------------------------------------
@bp.route("/elaborazioni", methods=["GET", "POST"])
def elaborazioni():
    if request.method == "POST":
        anno = request.form.get("anno", type=int)
        mese = request.form.get("mese", type=int)
        tipo = f_str("tipo", "ordinaria")
        if not anno or not mese or not 1 <= mese <= 12:
            flash("Indica anno e mese.", "danger")
            return redirect(url_for("main.elaborazioni"))
        esiste = Elaborazione.query.filter_by(workspace_id=g.ws.id, anno=anno, mese=mese, tipo=tipo).first()
        if esiste:
            flash("Questa elaborazione esiste già: l'ho aperta.", "info")
            return redirect(url_for("main.elaborazione", el_id=esiste.id))
        struttura_tipo = next((s for s in strutture_ws() if s.tipo_cedolino == tipo), None)
        if tipo != "ordinaria" and not struttura_tipo:
            flash(f"Non c'è una struttura retributiva di tipo '{tipo}'.", "danger")
            return redirect(url_for("main.elaborazioni"))
        el = Elaborazione(workspace_id=g.ws.id, anno=anno, mese=mese, tipo=tipo,
                          descrizione=f"{MESI[mese]} {anno} - {tipo}")
        db.session.add(el)
        n = _aggiungi_cedolini(el, struttura_tipo if tipo != "ordinaria" else None)
        db.session.commit()
        flash(f"Elaborazione creata con {n} cedolini in bozza. Inserisci le variabili del mese e calcola.",
              "success")
        return redirect(url_for("main.elaborazione", el_id=el.id))
    elenco = (Elaborazione.query.filter_by(workspace_id=g.ws.id)
              .order_by(Elaborazione.anno.desc(), Elaborazione.mese.desc(), Elaborazione.id.desc()).all())
    oggi = date.today()
    return render_template("elaborazioni.html", elenco=elenco, oggi=oggi)


def _aggiungi_cedolini(el, struttura_forzata):
    presenti = {c.dipendente_id for c in el.cedolini}
    n = 0
    for d in Dipendente.query.filter_by(workspace_id=g.ws.id, attivo=True).order_by(Dipendente.matricola):
        c = d.contratto_attivo
        if not c or d.id in presenti:
            continue
        ced = Cedolino(workspace_id=g.ws.id, elaborazione=el, dipendente=d, contratto=c,
                       struttura=struttura_forzata or c.struttura, anno=el.anno, mese=el.mese,
                       tipo=el.tipo, giorni_lavorati=26 if el.tipo == "ordinaria" else 0,
                       ore_lavorate=round(173 * (c.part_time or 0) / 100, 1) if el.tipo == "ordinaria" else 0)
        db.session.add(ced)
        n += 1
    return n


@bp.route("/elaborazioni/<int:el_id>", methods=["GET", "POST"])
def elaborazione(el_id):
    el = ws_get(Elaborazione, el_id)
    codici = INPUT_GRIGLIA.get(el.tipo, INPUT_CODES)
    if request.method == "POST":
        azione = request.form.get("azione", "salva")
        if azione == "aggiungi":
            st = next((s for s in strutture_ws() if s.tipo_cedolino == el.tipo), None) if el.tipo != "ordinaria" else None
            n = _aggiungi_cedolini(el, st)
            db.session.commit()
            flash(f"Aggiunti {n} cedolini.", "success" if n else "info")
            return redirect(url_for("main.elaborazione", el_id=el.id))
        if azione == "elimina":
            if any(c.stato == "confermato" for c in el.cedolini):
                flash("Ci sono cedolini confermati: riaprili prima di eliminare l'elaborazione.", "warning")
                return redirect(url_for("main.elaborazione", el_id=el.id))
            for c in list(el.cedolini):
                db.session.delete(c)
            db.session.delete(el)
            db.session.commit()
            flash("Elaborazione eliminata.", "success")
            return redirect(url_for("main.elaborazioni"))
        # salva variabili
        for ced in el.cedolini:
            if ced.stato == "confermato":
                continue
            ced.giorni_lavorati = f_float(f"g_{ced.id}", ced.giorni_lavorati)
            ced.ore_lavorate = f_float(f"o_{ced.id}", ced.ore_lavorate)
            esistenti = {i.codice: i for i in ced.inputs}
            for cod in codici:
                val = f_float(f"in_{ced.id}_{cod}")
                if val:
                    if cod in esistenti:
                        esistenti[cod].valore = val
                    else:
                        ced.inputs.append(CedolinoInput(codice=cod, valore=val))
                elif cod in esistenti:
                    db.session.delete(esistenti[cod])
        db.session.flush()
        msg = "Variabili salvate."
        if azione in ("calcola", "conferma"):
            ok = ko = 0
            for ced in el.cedolini:
                if ced.stato == "confermato":
                    continue
                db.session.refresh(ced)
                esito, _ = calcola(ced, commit=False)
                ok += esito
                ko += not esito
            msg = f"Calcolati {ok} cedolini" + (f", {ko} con errori" if ko else "") + "."
            if azione == "conferma":
                n = 0
                for ced in el.cedolini:
                    if ced.stato == "calcolato":
                        ced.stato = "confermato"
                        ced.confermato_at = now()
                        n += 1
                msg += f" Confermati {n}."
        db.session.commit()
        flash(msg, "success")
        return redirect(url_for("main.elaborazione", el_id=el.id))
    cedolini = sorted(el.cedolini, key=lambda c: c.dipendente.matricola if c.dipendente else "")
    tot = {k: sum(getattr(c, k) or 0 for c in cedolini if c.stato != "bozza") for k in ("lordo", "netto", "costo")}
    return render_template("elaborazione.html", el=el, cedolini=cedolini, codici=codici,
                           input_label=INPUT_LABEL, tot=tot)


# ---------------------------------------------------------------------------
# Cedolino
# ---------------------------------------------------------------------------
def contatori_ferie(ced):
    """Ferie e ROL: maturato nell'anno fino al mese del cedolino, goduto, residuo."""
    param = {p.codice: p.valore for p in Parametro.query.filter_by(workspace_id=g.ws.id)}
    ceds = (Cedolino.query.filter_by(workspace_id=g.ws.id, dipendente_id=ced.dipendente_id,
                                     anno=ced.anno, tipo="ordinaria")
            .filter(Cedolino.mese <= ced.mese).all())
    ceds = [c for c in ceds if c.stato != "bozza" or c.id == ced.id]
    pt = (ced.contratto.part_time if ced.contratto else 100) / 100
    out = {}
    for cod, par in (("FERIE", "FERIE_ORE_ANNUE"), ("ROL", "ROL_ORE_ANNUE")):
        maturato = param.get(par, 0) / 12 * len(ceds) * pt
        goduto = sum(c.input_map().get(cod, 0) for c in ceds)
        out[cod] = {"maturato": maturato, "goduto": goduto, "residuo": maturato - goduto}
    return out


@bp.route("/cedolini/<int:ced_id>", methods=["GET", "POST"])
def cedolino(ced_id):
    ced = ws_get(Cedolino, ced_id)
    if request.method == "POST":
        azione = request.form.get("azione", "calcola")
        if azione == "riapri":
            ced.stato = "calcolato"
            ced.confermato_at = None
            db.session.commit()
            flash("Cedolino riaperto: ora puoi modificarlo e ricalcolarlo.", "info")
            return redirect(url_for("main.cedolino", ced_id=ced.id))
        if ced.stato == "confermato":
            flash("Il cedolino è confermato. Riaprilo per modificarlo.", "warning")
            return redirect(url_for("main.cedolino", ced_id=ced.id))
        if azione == "elimina":
            el_id = ced.elaborazione_id
            db.session.delete(ced)
            db.session.commit()
            flash("Cedolino eliminato.", "success")
            return redirect(url_for("main.elaborazione", el_id=el_id) if el_id else url_for("main.dipendenti"))
        if azione == "conferma":
            if ced.stato != "calcolato":
                flash("Prima calcola il cedolino.", "warning")
            else:
                ced.stato = "confermato"
                ced.confermato_at = now()
                db.session.commit()
                flash("Cedolino confermato.", "success")
            return redirect(url_for("main.cedolino", ced_id=ced.id))
        ced.giorni_lavorati = f_float("giorni_lavorati", ced.giorni_lavorati)
        ced.ore_lavorate = f_float("ore_lavorate", ced.ore_lavorate)
        st_id = request.form.get("struttura_id", type=int)
        if st_id:
            ced.struttura = ws_get(Struttura, st_id)
        for i in list(ced.inputs):
            db.session.delete(i)
        db.session.flush()
        for cod in INPUT_CODES:
            val = f_float(f"in_{cod}")
            if val:
                ced.inputs.append(CedolinoInput(codice=cod, valore=val))
        db.session.flush()
        db.session.refresh(ced)
        ok, msg = calcola(ced)
        flash(msg, "success" if ok else "danger")
        return redirect(url_for("main.cedolino", ced_id=ced.id))
    regole = {}
    if ced.struttura:
        regole = {r.codice: r for r in ced.struttura.regole}
    return render_template("cedolino.html", ced=ced, inputs=ced.input_map(), catalogo=INPUT_CATALOGO,
                           strutture=strutture_ws(), regole=regole, contatori=contatori_ferie(ced))


@bp.route("/cedolini/<int:ced_id>/stampa")
def cedolino_stampa(ced_id):
    ced = ws_get(Cedolino, ced_id)
    return render_template("cedolino_stampa.html", ced=ced, contatori=contatori_ferie(ced))


@bp.route("/elaborazioni/<int:el_id>/stampa")
def elaborazione_stampa(el_id):
    el = ws_get(Elaborazione, el_id)
    ceds = [c for c in sorted(el.cedolini, key=lambda c: c.dipendente.matricola) if c.stato != "bozza"]
    return render_template("cedolino_stampa.html", cedolini=ceds, contatori_fn=contatori_ferie, ced=None)


# ---------------------------------------------------------------------------
# Strutture e regole
# ---------------------------------------------------------------------------
@bp.route("/strutture", methods=["GET", "POST"])
def strutture():
    if request.method == "POST":
        src_id = request.form.get("duplica", type=int)
        if src_id:
            src = ws_get(Struttura, src_id)
            n = 2
            while Struttura.query.filter_by(workspace_id=g.ws.id, codice=f"{src.codice}_{n}").first():
                n += 1
            copia = Struttura(workspace_id=g.ws.id, codice=f"{src.codice}_{n}", nome=f"{src.nome} (copia)",
                              tipo_cedolino=src.tipo_cedolino, descrizione=src.descrizione)
            for r in src.regole:
                copia.regole.append(Regola(
                    workspace_id=g.ws.id, sequenza=r.sequenza, codice=r.codice, nome=r.nome,
                    categoria=r.categoria, condizione=r.condizione, formula=r.formula,
                    quantita_formula=r.quantita_formula, base_formula=r.base_formula, stampa=r.stampa,
                    registro=r.registro, note=r.note, attiva=r.attiva))
            db.session.add(copia)
            db.session.commit()
            flash("Struttura duplicata: puoi modificarla senza toccare l'originale.", "success")
            return redirect(url_for("main.struttura", st_id=copia.id))
    return render_template("strutture.html", elenco=strutture_ws())


@bp.route("/strutture/<int:st_id>", methods=["GET", "POST"])
def struttura(st_id):
    st = ws_get(Struttura, st_id)
    if request.method == "POST":
        azione = request.form.get("azione")
        if azione == "salva":
            st.nome = f_str("nome") or st.nome
            st.descrizione = f_str("descrizione")
            st.tipo_cedolino = f_str("tipo_cedolino", st.tipo_cedolino)
            db.session.commit()
            flash("Struttura aggiornata.", "success")
        elif azione == "ricalcola":
            ok = ko = 0
            for ced in Cedolino.query.filter_by(workspace_id=g.ws.id, struttura_id=st.id):
                if ced.stato == "confermato":
                    continue
                esito, _ = calcola(ced, commit=False)
                ok += esito
                ko += not esito
            db.session.commit()
            flash(f"Ricalcolati {ok} cedolini non confermati" + (f", {ko} con errori" if ko else "") + ".",
                  "success" if not ko else "warning")
        elif azione == "elimina":
            usata = (Contratto.query.filter_by(struttura_id=st.id).first()
                     or Cedolino.query.filter_by(struttura_id=st.id).first())
            if usata:
                flash("La struttura è usata da contratti o cedolini: non si può eliminare.", "warning")
            else:
                db.session.delete(st)
                db.session.commit()
                flash("Struttura eliminata.", "success")
                return redirect(url_for("main.strutture"))
        return redirect(url_for("main.struttura", st_id=st.id))
    return render_template("struttura.html", st=st)


@bp.route("/strutture/<int:st_id>/regola/nuova", methods=["GET", "POST"])
@bp.route("/regole/<int:reg_id>", methods=["GET", "POST"])
def regola_form(st_id=None, reg_id=None):
    if reg_id:
        r = ws_get(Regola, reg_id)
        st = r.struttura
    else:
        st = ws_get(Struttura, st_id)
        r = None
    cats = Categoria.query.filter_by(workspace_id=g.ws.id).order_by(Categoria.sequenza).all()
    if request.method == "POST":
        if request.form.get("azione") == "elimina" and r:
            db.session.delete(r)
            db.session.commit()
            flash(f"Regola {r.codice} eliminata.", "success")
            return redirect(url_for("main.struttura", st_id=st.id))
        codice = f_str("codice").upper().replace(" ", "_")
        dati = {
            "sequenza": int(f_float("sequenza", 100)),
            "codice": codice, "nome": f_str("nome"),
            "condizione": request.form.get("condizione", ""),
            "formula": request.form.get("formula", "") or "0",
            "quantita_formula": request.form.get("quantita_formula", ""),
            "base_formula": request.form.get("base_formula", ""),
            "stampa": request.form.get("stampa") == "on",
            "attiva": request.form.get("attiva") == "on",
            "registro": f_str("registro"), "note": f_str("note"),
        }
        errori = valida_formule([("Condizione", dati["condizione"]), ("Formula", dati["formula"]),
                                 ("Quantità", dati["quantita_formula"]), ("Base", dati["base_formula"])])
        if not codice.replace("_", "").isalnum() or not codice[:1].isalpha():
            errori.append("Il codice deve iniziare con una lettera e contenere solo lettere, numeri e _.")
        if not dati["nome"]:
            errori.append("Il nome è obbligatorio.")
        doppione = Regola.query.filter_by(struttura_id=st.id, codice=codice).first()
        if doppione and (r is None or doppione.id != r.id):
            errori.append(f"Esiste già una regola {codice} in questa struttura.")
        cat_id = request.form.get("categoria_id", type=int)
        cat = ws_get(Categoria, cat_id) if cat_id else None
        if errori:
            for e in errori:
                flash(e, "danger")
            bozza = Regola(**dati)
            bozza.categoria = cat
            bozza.id = r.id if r else None
            return render_template("regola_form.html", r=bozza, st=st, cats=cats, nuova=r is None)
        if r is None:
            r = Regola(workspace_id=g.ws.id, struttura=st)
            db.session.add(r)
        for k, v in dati.items():
            setattr(r, k, v)
        r.categoria = cat
        db.session.commit()
        flash(f"Regola {r.codice} salvata. Usa 'Ricalcola i cedolini' per vederne l'effetto.", "success")
        return redirect(url_for("main.struttura", st_id=st.id))
    return render_template("regola_form.html", r=r, st=st, cats=cats, nuova=r is None)


# ---------------------------------------------------------------------------
# Tabelle e dati azienda
# ---------------------------------------------------------------------------
@bp.route("/tabelle", methods=["GET", "POST"])
def tabelle():
    ws_id = g.ws.id
    if request.method == "POST":
        sez = request.form.get("sezione")
        if sez == "azienda":
            for campo in ("ragione_sociale", "partita_iva", "indirizzo", "ccnl", "pat_inail", "matricola_inps"):
                setattr(g.ws, campo, f_str(campo))
        elif sez == "parametri":
            for p in Parametro.query.filter_by(workspace_id=ws_id):
                p.valore = f_float(f"p_{p.id}", p.valore)
            cod = f_str("nuovo_codice").upper().replace(" ", "_")
            if cod:
                if Parametro.query.filter_by(workspace_id=ws_id, codice=cod).first():
                    flash("Parametro già esistente.", "warning")
                else:
                    db.session.add(Parametro(workspace_id=ws_id, codice=cod, descrizione=f_str("nuovo_descr"),
                                             valore=f_float("nuovo_valore"), unita=f_str("nuovo_unita")))
        elif sez == "scaglioni":
            for s in ScaglioneIrpef.query.filter_by(workspace_id=ws_id):
                if request.form.get(f"del_{s.id}") == "on":
                    db.session.delete(s)
                    continue
                s.da = f_float(f"da_{s.id}", s.da)
                a = (request.form.get(f"a_{s.id}") or "").strip()
                s.a = f_float(f"a_{s.id}") if a else None
                s.aliquota = f_float(f"al_{s.id}", s.aliquota)
            if (request.form.get("nuovo_aliq") or "").strip():
                a = (request.form.get("nuovo_a") or "").strip()
                db.session.add(ScaglioneIrpef(workspace_id=ws_id, da=f_float("nuovo_da"),
                                              a=f_float("nuovo_a") if a else None,
                                              aliquota=f_float("nuovo_aliq")))
        elif sez == "livelli":
            for lv in Livello.query.filter_by(workspace_id=ws_id):
                lv.descrizione = f_str(f"ld_{lv.id}", lv.descrizione)
                lv.minimo = f_float(f"lm_{lv.id}", lv.minimo)
                lv.scatto_importo = f_float(f"ls_{lv.id}", lv.scatto_importo)
            cod = f_str("nuovo_livello").upper()
            if cod:
                db.session.add(Livello(workspace_id=ws_id, codice=cod, descrizione=f_str("nuovo_livello_descr"),
                                       minimo=f_float("nuovo_livello_minimo"),
                                       scatto_importo=f_float("nuovo_livello_scatto")))
            if request.form.get("aggiorna_contratti") == "on":
                n = 0
                for c in Contratto.query.filter_by(workspace_id=ws_id, attivo=True):
                    if c.livello:
                        c.minimo = c.livello.minimo
                        c.scatto_importo = c.livello.scatto_importo
                        n += 1
                flash(f"Aggiornati minimo e scatto su {n} contratti attivi.", "info")
        elif sez == "categorie":
            for cat in Categoria.query.filter_by(workspace_id=ws_id):
                cat.nome = f_str(f"cn_{cat.id}", cat.nome)
                cat.tipo = f_str(f"ct_{cat.id}", cat.tipo)
                cat.sequenza = int(f_float(f"cs_{cat.id}", cat.sequenza))
            cod = f_str("nuova_cat").upper()
            if cod:
                db.session.add(Categoria(workspace_id=ws_id, codice=cod, nome=f_str("nuova_cat_nome") or cod,
                                         tipo=f_str("nuova_cat_tipo", "info"), sequenza=200))
        db.session.commit()
        flash("Tabelle aggiornate. Ricalcola i cedolini non confermati per applicare le modifiche.", "success")
        return redirect(url_for("main.tabelle", _anchor=sez))
    return render_template(
        "tabelle.html",
        parametri=Parametro.query.filter_by(workspace_id=ws_id).order_by(Parametro.id).all(),
        scaglioni=ScaglioneIrpef.query.filter_by(workspace_id=ws_id).order_by(ScaglioneIrpef.da).all(),
        livelli=livelli_ws(),
        categorie=Categoria.query.filter_by(workspace_id=ws_id).order_by(Categoria.sequenza).all())


# ---------------------------------------------------------------------------
# Riepilogo versamenti (F24, INPS) e costi del mese
# ---------------------------------------------------------------------------
@bp.route("/riepilogo")
def riepilogo():
    ws_id = g.ws.id
    periodi = (db.session.query(Cedolino.anno, Cedolino.mese).filter_by(workspace_id=ws_id)
               .distinct().order_by(Cedolino.anno.desc(), Cedolino.mese.desc()).all())
    anno = request.args.get("anno", type=int) or (periodi[0][0] if periodi else date.today().year)
    mese = request.args.get("mese", type=int) or (periodi[0][1] if periodi else date.today().month)
    anche_calcolati = request.args.get("calcolati") == "1"
    stati = ["confermato", "calcolato"] if anche_calcolati else ["confermato"]
    ceds = (Cedolino.query.filter_by(workspace_id=ws_id, anno=anno, mese=mese)
            .filter(Cedolino.stato.in_(stati)).all())
    ceds.sort(key=lambda c: (c.dipendente.matricola, c.tipo))

    registri = OrderedDict()
    for ced in ceds:
        for r in ced.righe:
            if not r.registro:
                continue
            key = (r.registro, r.codice)
            item = registri.setdefault(key, {"registro": r.registro, "codice": r.codice, "nome": r.nome,
                                             "importo": 0.0, "n": 0})
            item["importo"] += r.importo
            item["n"] += 1
    righe_registri = sorted(registri.values(), key=lambda x: (x["registro"], x["codice"]))

    erario = defaultdict(float)
    crediti = defaultdict(float)
    inps = {"dipendente": 0.0, "azienda": 0.0}
    altri = defaultdict(float)
    for it in righe_registri:
        reg = it["registro"]
        if reg.lower().startswith("erario"):
            erario[reg.split(" ", 1)[1] if " " in reg else reg] += it["importo"]
        elif reg.lower().startswith("credito"):
            crediti[reg.split(" ", 1)[1] if " " in reg else reg] += it["importo"]
        elif reg.upper() == "INPS":
            if it["codice"] == "INPS_DITTA":
                inps["azienda"] += it["importo"]
            else:
                inps["dipendente"] += it["importo"]
        else:
            altri[reg] += it["importo"]
    tot_erario = sum(erario.values())
    tot_crediti = sum(crediti.values())
    tot_inps = inps["dipendente"] + inps["azienda"]
    sintesi = {"lordo": sum(c.lordo for c in ceds), "netto": sum(c.netto for c in ceds),
               "costo": sum(c.costo for c in ceds)}
    scad_mese, scad_anno = (mese % 12) + 1, anno + (1 if mese == 12 else 0)
    return render_template(
        "riepilogo.html", anno=anno, mese=mese, periodi=periodi, ceds=ceds, righe_registri=righe_registri,
        erario=dict(erario), crediti=dict(crediti), inps=inps, altri=dict(altri), tot_erario=tot_erario,
        tot_crediti=tot_crediti, tot_inps=tot_inps, saldo_f24=tot_erario - tot_crediti + tot_inps,
        sintesi=sintesi, anche_calcolati=anche_calcolati, scadenza=date(scad_anno, scad_mese, 16))
