"""Controllo del costo del personale: i numeri del controller sulle buste paga completate.

Tutto parte dalle buste in stato «Completata» del periodo scelto (le note di credito si sottraggono):
  - costo aziendale (regola COSTO), lordo (categoria GROSS), contributi c/azienda (INPS_DITTA, INAIL), TFR;
  - ore dai giorni lavorati: ore teoriche dell'orario, assenze per tipo, ore pagate, ore lavorate davvero;
  - ore di straordinario dagli apporti che iniziano con STR (STR25, STR50…).

Da qui: costo pieno per dipendente e per reparto, costo orario pagato ed effettivo, assenteismo, straordinari,
budget del personale con lo scostamento diviso in effetto ore ed effetto costo orario, turnover e formazione,
simulazione del premio di risultato legato ai KPI.
"""
from collections import defaultdict
from datetime import date

from .models import Cessazione, Corso, CorsoPartecipante, Employee, LeaveType, Payslip

# assenze «fisiologiche» (non sono assenteismo): ferie, permessi retribuiti, festività
FISIOLOGICHE = {"FERIE", "ROL", "GLOBAL", "FEST"}
ORE_GIORNO_TEMPO_PIENO = 8.0

MESI_BREVI = ["", "gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]

# parametri modificabili dall'allievo (salvati nell'ambiente, pagina Parametri del controllo)
PARAMETRI_DEFAULT = {
    "soglia_assenteismo": 4.0,        # % oltre la quale si accende l'allarme
    "soglia_straordinari": 8.0,       # % delle ore lavorate
    "turnover_selezione": 2500.0,     # € per ricerca e selezione di un sostituto
    "turnover_mesi_inserimento": 3.0, # mesi per arrivare a piena produttività
    "turnover_produttivita_persa": 40.0,  # % media di produttività persa nei mesi di inserimento
    "turnover_formazione": 800.0,     # € di formazione iniziale
    "premio_massimo": 1200.0,         # € lordi per dipendente a tempo pieno
    "premio_peso_presenza": 40.0,     # % del premio legata all'assenteismo individuale
    "premio_peso_straordinari": 20.0, # % legata a straordinari sotto soglia (organizzazione del lavoro)
    "premio_peso_aziendale": 40.0,    # % legata all'obiettivo aziendale (es. margine, scarti, consegne)
    "premio_obiettivo_aziendale": 80.0,   # % di raggiungimento dell'obiettivo aziendale
    "premio_aliquota_sostitutiva": 1.0,   # % imposta sostitutiva sui premi di risultato (2026-2027, verificare)
    "premio_limite_detassazione": 5000.0, # € massimo agevolabile per dipendente (verificare)
}


def _f(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _vuoto():
    return {"costo": 0.0, "lordo": 0.0, "inps_ditta": 0.0, "inail": 0.0, "tfr": 0.0, "str_euro": 0.0,
            "ore_teoriche": 0.0, "ore_pagate": 0.0, "ore_lavorate": 0.0, "ore_str": 0.0, "fte_mesi": 0.0,
            "ass": defaultdict(float), "buste": 0, "mesi": set()}


def buste_periodo(ws_id, anno, mese_da=1, mese_a=12):
    d1, d2 = date(anno, mese_da, 1), date(anno, mese_a, 28)
    q = (Payslip.query.filter(Payslip.workspace_id == ws_id, Payslip.state == "done",
                              Payslip.date_from >= d1, Payslip.date_from <= d2)
         .order_by(Payslip.employee_id, Payslip.date_from))
    return q.all()


def periodi_disponibili(ws_id):
    return sorted({(s.date_from.year, s.date_from.month)
                   for s in Payslip.query.filter_by(workspace_id=ws_id, state="done")}, reverse=True)


def analizza_busta(slip, non_retribuite):
    """Numeri di una busta (segno meno per le note di credito)."""
    sg = -1.0 if slip.credit_note else 1.0
    codici = defaultdict(float)
    cat = defaultdict(float)
    for ln in slip.line_ids:
        codici[ln.code] += ln.total
        c = ln.category
        while c is not None:
            if c.code:
                cat[c.code] += ln.total
            c = c.parent
    r = {"costo": sg * codici.get("COSTO", 0.0), "lordo": sg * cat.get("GROSS", 0.0),
         "inps_ditta": sg * codici.get("INPS_DITTA", 0.0), "inail": sg * codici.get("INAIL", 0.0),
         "tfr": sg * codici.get("TFR", 0.0), "str_euro": sg * cat.get("STR", 0.0)}
    work_h = work_d = 0.0
    altre = {}
    for w in slip.worked_days_line_ids:
        if w.code == "WORK100":
            work_h += w.number_of_hours or 0.0
            work_d += w.number_of_days or 0.0
        else:
            altre[w.code] = altre.get(w.code, 0.0) + (w.number_of_hours or 0.0)
    # giorni lavorati «negativi» (come Odoo): WORK100 pieno e assenze in negativo; «positivi»: WORK100 già netto
    teoriche = work_h + sum(h for h in altre.values() if h > 0)
    ass = {k: abs(h) for k, h in altre.items() if abs(h) > 1e-9}
    non_pagate = sum(h for k, h in ass.items() if k in non_retribuite)
    ore_str = sum(i.amount or 0.0 for i in slip.input_line_ids if (i.code or "").upper().startswith("STR"))
    r.update({"ore_teoriche": sg * teoriche, "ore_pagate": sg * (teoriche - non_pagate),
              "ore_lavorate": sg * (teoriche - sum(ass.values())), "ore_str": sg * ore_str,
              "fte_mesi": sg * (teoriche / (work_d * ORE_GIORNO_TEMPO_PIENO) if work_d else 0.0),
              "ass": {k: sg * h for k, h in ass.items()}})
    return r


def _somma(acc, r, slip):
    for k in ("costo", "lordo", "inps_ditta", "inail", "tfr", "str_euro", "ore_teoriche", "ore_pagate",
              "ore_lavorate", "ore_str", "fte_mesi"):
        acc[k] += r[k]
    for k, h in r["ass"].items():
        acc["ass"][k] += h
    acc["buste"] += 1
    acc["mesi"].add(slip.date_from.month)


def indicatori(a, nmesi=None):
    """Indicatori da un accumulo (dipendente, reparto o azienda)."""
    nm = nmesi or max(1, len(a["mesi"]))
    lav_tot = a["ore_lavorate"] + a["ore_str"]
    assenteismo_h = sum(h for k, h in a["ass"].items() if k not in FISIOLOGICHE)
    fisiologiche_h = sum(h for k, h in a["ass"].items() if k in FISIOLOGICHE)
    costo_orario_pagato = a["costo"] / a["ore_pagate"] if a["ore_pagate"] > 0 else None
    return {
        **{k: a[k] for k in ("costo", "lordo", "inps_ditta", "inail", "tfr", "str_euro", "ore_teoriche",
                             "ore_pagate", "ore_lavorate", "ore_str")},
        "oneri": a["inps_ditta"] + a["inail"],
        "fte": a["fte_mesi"] / nm,
        "mesi": nm,
        "ore_lavorate_tot": lav_tot,
        "incidenza_oneri": (a["costo"] - a["lordo"]) / a["lordo"] if a["lordo"] else None,
        "costo_orario_pagato": costo_orario_pagato,
        "costo_orario_effettivo": a["costo"] / lav_tot if lav_tot > 0 else None,
        "costo_mensile_fte": a["costo"] / (a["fte_mesi"]) if a["fte_mesi"] > 0 else None,
        "assenteismo": assenteismo_h / a["ore_teoriche"] if a["ore_teoriche"] > 0 else None,
        "assenteismo_h": assenteismo_h,
        "fisiologiche_h": fisiologiche_h,
        "costo_assenze": (assenteismo_h * costo_orario_pagato) if costo_orario_pagato else 0.0,
        "straordinari": a["ore_str"] / lav_tot if lav_tot > 0 else None,
        "straordinari_lordo": a["str_euro"] / a["lordo"] if a["lordo"] else None,
        "ass": dict(a["ass"]),
    }


def analisi(ws_id, anno, mese_da=1, mese_a=12):
    """Analisi completa del periodo: per dipendente, per reparto, per mese e totale azienda."""
    non_retribuite = {t.code for t in LeaveType.query.filter_by(workspace_id=ws_id, unpaid=True)}
    per_dip, per_rep, per_mese, tot = {}, {}, {}, _vuoto()
    dipendenti = {}
    for s in buste_periodo(ws_id, anno, mese_da, mese_a):
        r = analizza_busta(s, non_retribuite)
        e = s.employee
        dipendenti[e.id] = e
        rep = (s.contract.department if s.contract and s.contract.department else e.department) or "Senza reparto"
        for chiave, d in ((e.id, per_dip), (rep, per_rep), (s.date_from.month, per_mese)):
            d.setdefault(chiave, _vuoto())
            _somma(d[chiave], r, s)
        _somma(tot, r, s)
    nmesi = max(1, len(tot["mesi"]))
    righe_dip = []
    for eid, a in per_dip.items():
        e = dipendenti[eid]
        righe_dip.append({"e": e, "reparto": e.department or "Senza reparto", **indicatori(a, nmesi)})
    righe_dip.sort(key=lambda x: (x["reparto"], x["e"].last_name))
    righe_rep = sorted(({"reparto": k, "dipendenti": len({r["e"].id for r in righe_dip if r["reparto"] == k}),
                         **indicatori(a, nmesi)} for k, a in per_rep.items()), key=lambda x: -x["costo"])
    righe_mese = [{"mese": m, "nome": MESI_BREVI[m], **indicatori(per_mese[m], 1)} for m in sorted(per_mese)]
    return {"anno": anno, "mese_da": mese_da, "mese_a": mese_a, "mesi": sorted(tot["mesi"]),
            "dipendenti": righe_dip, "reparti": righe_rep, "per_mese": righe_mese,
            "totale": indicatori(tot, nmesi), "vuoto": not righe_dip}


def tipi_assenza(ws_id):
    return {t.code: t.name for t in LeaveType.query.filter_by(workspace_id=ws_id)} | {"GLOBAL": "Festività"}


# ---------------------------------------------------------------------------- budget del personale
def budget_da_consuntivo(an):
    """Proposta di budget mensile per reparto: la media del periodo analizzato."""
    out = {}
    for r in an["reparti"]:
        nm = r["mesi"] or 1
        out[r["reparto"]] = {"fte": round(r["fte"], 2), "ore_mese": round(r["ore_lavorate_tot"] / nm, 1),
                             "costo_mese": round(r["costo"] / nm, 2)}
    return out


def confronto_budget(an, budget):
    """Budget contro consuntivo per reparto, con lo scostamento diviso in due effetti (logica del controller):
       effetto ore         = (ore effettive − ore budget) × costo orario budget
       effetto costo orario = (costo orario effettivo − costo orario budget) × ore effettive
    La somma dei due effetti è lo scostamento totale."""
    nm = max(1, len(an["mesi"]))
    righe = []
    reparti = {r["reparto"]: r for r in an["reparti"]}
    for rep in sorted(set(reparti) | set(budget or {})):
        b = (budget or {}).get(rep, {})
        c_b = _f(b.get("costo_mese")) * nm
        h_b = _f(b.get("ore_mese")) * nm
        r = reparti.get(rep)
        c_e = r["costo"] if r else 0.0
        h_e = r["ore_lavorate_tot"] if r else 0.0
        co_b = c_b / h_b if h_b else 0.0
        co_e = c_e / h_e if h_e else 0.0
        eff_ore = (h_e - h_b) * co_b
        eff_costo = (co_e - co_b) * h_e
        righe.append({"reparto": rep, "fte_b": _f(b.get("fte")), "fte_e": r["fte"] if r else 0.0,
                      "costo_b": c_b, "costo_e": c_e, "ore_b": h_b, "ore_e": h_e, "co_b": co_b, "co_e": co_e,
                      "scost": c_e - c_b, "eff_ore": eff_ore, "eff_costo": eff_costo,
                      "scost_pct": (c_e - c_b) / c_b if c_b else None})
    tot = {k: sum(r[k] for r in righe) for k in ("costo_b", "costo_e", "ore_b", "ore_e", "scost", "eff_ore",
                                                 "eff_costo", "fte_b", "fte_e")}
    tot["scost_pct"] = tot["scost"] / tot["costo_b"] if tot["costo_b"] else None
    return righe, tot


# ---------------------------------------------------------------------------- turnover e formazione
def turnover_formazione(ws_id, anno, an, par):
    cess = (Cessazione.query.filter(Cessazione.workspace_id == ws_id, Cessazione.data >= date(anno, 1, 1),
                                    Cessazione.data <= date(anno, 12, 31)).order_by(Cessazione.data).all())
    organico = max(1.0, an["totale"]["fte"]) if not an["vuoto"] else max(1, Employee.query.filter_by(workspace_id=ws_id).count())
    costo_mese_medio = (an["totale"]["costo_mensile_fte"] or 0.0)
    costo_uscita = (_f(par["turnover_selezione"]) + _f(par["turnover_formazione"])
                    + _f(par["turnover_mesi_inserimento"]) * costo_mese_medio * _f(par["turnover_produttivita_persa"]) / 100)
    corsi = (Corso.query.filter(Corso.workspace_id == ws_id, Corso.stato != "annullato")
             .filter((Corso.data_inizio == None) | ((Corso.data_inizio >= date(anno, 1, 1)) & (Corso.data_inizio <= date(anno, 12, 31))))  # noqa: E711
             .order_by(Corso.data_inizio).all())
    righe_corsi = []
    for c in corsi:
        n = CorsoPartecipante.query.filter_by(corso_id=c.id).count()
        righe_corsi.append({"c": c, "partecipanti": n, "ore_persona": (c.ore or 0) * n,
                            "costo_persona": (c.costo or 0) / n if n else None})
    costo_form = sum(_f(r["c"].costo) for r in righe_corsi)
    ore_form = sum(r["ore_persona"] for r in righe_corsi)
    return {"cessazioni": cess, "uscite": len(cess), "organico": organico,
            "turnover": len(cess) / organico if organico else 0.0,
            "costo_uscita": costo_uscita, "costo_turnover": costo_uscita * len(cess),
            "costo_mese_medio": costo_mese_medio,
            "corsi": righe_corsi, "costo_formazione": costo_form, "ore_formazione": ore_form,
            "formazione_fte": costo_form / organico if organico else 0.0,
            "ore_formazione_fte": ore_form / organico if organico else 0.0}


# ---------------------------------------------------------------------------- premio di risultato
def premio(an, par):
    """Simulazione del premio di risultato legato ai KPI.

    Quota presenza: piena se l'assenteismo individuale è entro la soglia, ridotta in proporzione fino a zero
    al doppio della soglia. Quota straordinari: piena se gli straordinari sono entro la soglia (lavoro organizzato,
    non rincorso), zero oltre il doppio. Quota aziendale: % di raggiungimento dell'obiettivo comune.
    Il premio è riproporzionato all'FTE (part-time). Costo aziendale = premio × (costo / lordo) del dipendente."""
    soglia_a = _f(par["soglia_assenteismo"]) / 100
    soglia_s = _f(par["soglia_straordinari"]) / 100
    pmax = _f(par["premio_massimo"])
    pesi = (_f(par["premio_peso_presenza"]) / 100, _f(par["premio_peso_straordinari"]) / 100,
            _f(par["premio_peso_aziendale"]) / 100)
    aziendale = max(0.0, min(1.0, _f(par["premio_obiettivo_aziendale"]) / 100))

    def scala(valore, soglia):
        if valore is None:
            return 1.0
        if valore <= soglia:
            return 1.0
        if soglia <= 0 or valore >= 2 * soglia:
            return 0.0
        return 1.0 - (valore - soglia) / soglia

    righe = []
    for d in an["dipendenti"]:
        q_pres = scala(d["assenteismo"], soglia_a)
        q_str = scala(d["straordinari"], soglia_s)
        raggiunto = pesi[0] * q_pres + pesi[1] * q_str + pesi[2] * aziendale
        fte = min(1.0, d["fte"] or 0.0)
        lordo_premio = pmax * raggiunto * fte
        moltiplicatore = d["costo"] / d["lordo"] if d["lordo"] else 1.0
        agevolato = min(lordo_premio, _f(par["premio_limite_detassazione"]))
        righe.append({"e": d["e"], "reparto": d["reparto"], "q_pres": q_pres, "q_str": q_str, "raggiunto": raggiunto,
                      "fte": fte, "premio": lordo_premio, "costo_azienda": lordo_premio * moltiplicatore,
                      "imposta": agevolato * _f(par["premio_aliquota_sostitutiva"]) / 100})
    tot = {k: sum(r[k] for r in righe) for k in ("premio", "costo_azienda", "imposta")}
    annuo = an["totale"]["costo"] / max(1, len(an["mesi"])) * 12   # il premio è annuale: si confronta con il costo di un anno
    tot["costo_annuo_stimato"] = annuo
    tot["costo_su_personale"] = tot["costo_azienda"] / annuo if annuo else None
    return righe, tot
