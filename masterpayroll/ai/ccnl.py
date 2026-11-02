"""Assistente CCNL e seconda opinione, sulla banca dati di ccnl-engine (Lucas Puerari, licenza MIT).

1. Schede: dalle regole strutturate dei tre CCNL del corso (metalmeccanico Federmeccanica, commercio Confcommercio,
   logistica Confetra) si costruiscono schede in italiano con valore, articolo, pagina, citazione testuale, documento e
   stato di verifica. La ricerca è locale (punteggio BM25 sulle parole, con sinonimi): la risposta è sempre una scheda con
   la sua fonte, mai un testo inventato. Un modello linguistico, se attivo, può solo riformulare la scheda trovata.
2. Seconda opinione: il motore di ccnl-engine calcola la busta di novembre 2026 di ogni dipendente e la si confronta con
   MasterPayroll (minimo, scatti, contributi c/azienda, TFR).

ccnl-engine è in versione alpha e molti dati sono estratti con l'AI e non ancora revisionati da una persona: nel corso è
una seconda opinione da verificare, non la verità.
"""
import gzip
import json
import math
import re
from collections import Counter
from datetime import date
from functools import lru_cache

CONTRATTI = {
    "metalmeccanico-federmeccanica": "Metalmeccanico industria (Federmeccanica-Assistal)",
    "commercio-confcommercio": "Terziario, distribuzione e servizi (Confcommercio)",
    "logistica-trasporto-confetra": "Logistica, trasporto merci e spedizione (Confetra)",
}
DATA_RIF = date(2026, 11, 1)
STATI = {"verified": "verificato sulla fonte", "derived": "ricavato", "assumed": "ipotizzato", "missing": "mancante"}


def disponibile():
    try:
        import ccnl_engine  # noqa: F401
        return True
    except ImportError:
        return False


@lru_cache(maxsize=8)
def dati(cid):
    import importlib.resources as R
    base = R.files("ccnl_engine") / "knowledge" / "agreement"
    gz = base / f"{cid}.json.gz"
    if gz.is_file():
        return json.loads(gzip.decompress(gz.read_bytes()))
    return json.loads((base / f"{cid}.json").read_text(encoding="utf-8"))


def _periodo(periods, rif=DATA_RIF):
    """Il valore in vigore alla data di riferimento (o l'ultimo noto)."""
    scelto = None
    for p in periods or []:
        da = date.fromisoformat(p.get("valid_from", "1900-01-01"))
        a = date.fromisoformat(p["valid_until"]) if p.get("valid_until") else None
        if da <= rif and (a is None or rif < a):
            scelto = p
    return scelto or (periods[-1] if periods else None)


_TRADUZIONI_FONTE = [(r"\brate table\b", "tabella delle maggiorazioni"), (r"\btable row\b", "tabella, riga"),
                     (r"\btable\b", "tabella"), (r"\band\b", "e"), (r"\bpage\b", "pagina"), (r"\brow\b", "riga")]


def _italiano(testo):
    """Le citazioni di ccnl-engine hanno qualche parola inglese nelle indicazioni di sezione: si traducono."""
    for rx, it in _TRADUZIONI_FONTE:
        testo = re.sub(rx, it, testo or "")
    return testo


DATI_MANCANTI = {
    "addizionale_comunale": "comune per l'addizionale comunale", "addizionale_regionale": "regione per l'addizionale regionale",
    "family_deductions": "familiari a carico", "inps_employee": "contributi INPS di altri rapporti di lavoro",
    "inps_employer": "categoria INPS dell'azienda", "pension_fund_contribution": "adesione al fondo pensione",
    "rinnovo_substitute_tax": "imposta sostitutiva sugli aumenti del rinnovo", "tfr": "fondo di tesoreria INPS del TFR",
    "tfr_revaluation": "fondo TFR accumulato (rivalutazione)", "ulteriore_detrazione_lavoro": "redditi dell'anno (ulteriore detrazione)",
    "seniority": "anzianità di servizio", "somma_esente": "somma esente del cuneo fiscale", "base_salary": "minimo tabellare",
}


def traduci_dato(codice):
    return DATI_MANCANTI.get(codice, (codice or "").replace("_", " "))


def _fonte(prov):
    if not prov:
        return None
    loc = prov.get("location") or {}
    doc = loc.get("source_document") or {}
    return {"sezione": _italiano(loc.get("section", "")), "pagina": loc.get("page", ""), "citazione": loc.get("quote", ""),
            "documento": doc.get("title", ""), "url": doc.get("url", ""), "stato": STATI.get(prov.get("status"), prov.get("status", ""))}


def _eur(x):
    try:
        return f"{float(x):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return str(x)


def _pct(x):
    try:
        return f"{float(x) * 100:g}%".replace(".", ",")
    except (TypeError, ValueError):
        return str(x)


def schede(cid):
    d = dati(cid)
    nome = CONTRATTI.get(cid, d["meta"]["name"])
    p, w = d.get("parameters", {}), d.get("work_rules", {})
    out = []

    def add(titolo, testo, chiavi, prov, tema):
        out.append({"ccnl": cid, "contratto": nome, "titolo": titolo, "testo": testo, "chiavi": chiavi, "fonte": _fonte(prov),
                    "tema": tema})

    righe = []
    prov_min = None
    for lv in d.get("levels", []):
        per = _periodo((lv.get("base_salary") or {}).get("periods"))
        if per:
            righe.append(f"{lv['code']}: {_eur(per['value'])}")
            prov_min = prov_min or per.get("provenance") or lv.get("provenance")
    if righe:
        add("Minimi tabellari (paga base) per livello", f"Paga base mensile in vigore a novembre 2026 — {'; '.join(righe)}. "
            "Non comprende gli altri elementi fissi previsti da alcuni contratti (per esempio contingenza ed EDR nel "
            "commercio): vanno sommati per avere la retribuzione minima.",
            "minimo minimi tabellare retribuzione paga base stipendio livello livelli tabella", prov_min, "retribuzione")
    hd = _periodo((p.get("hourly_divisor") or {}).get("periods"))
    if hd:
        add("Divisore orario", f"La paga oraria si ottiene dividendo la retribuzione mensile per {hd['value']}.",
            "divisore orario paga oraria quota oraria ora", hd.get("provenance"), "retribuzione")
    am = _periodo((p.get("additional_months") or {}).get("periods"))
    if am:
        add("Mensilità annue", f"Le mensilità annue sono {am['value']} (tredicesima{' e quattordicesima' if str(am['value']).startswith('14') else ''}).",
            "mensilità tredicesima quattordicesima mensilita aggiuntive", am.get("provenance"), "retribuzione")
    si = p.get("seniority_increments") or {}
    if si:
        imp = []
        for lv, v in (si.get("amount_by_level") or {}).items():
            per = _periodo(v.get("periods"))
            if per:
                imp.append(f"{lv}: {_eur(per['value'])}")
        cad = si.get("cadence_months")
        add("Scatti di anzianità", f"Uno scatto ogni {cad} mesi di anzianità" if cad else "Scatti di anzianità",
            "scatti scatto anzianità aumenti periodici biennio bienni triennio", si.get("provenance"), "retribuzione")
        out[-1]["testo"] += (f", fino a un massimo di {si.get('maximum_count')} scatti" if si.get("maximum_count") else "") + \
            (f". Importo per livello: {'; '.join(imp)}." if imp else ".")
    ts = w.get("time_supplements") or {}
    for b in ts.get("overtime_bands") or []:
        per = _periodo((b.get("rate") or {}).get("periods"))
        if per:
            add(f"Straordinario · {b.get('description', b.get('code'))}",
                f"Maggiorazione {_pct(per['value'])} ({b.get('description', '')}).",
                "straordinario straordinari ore extra maggiorazione lavoro supplementare oltre orario notturno festivo " +
                " ".join(b.get("applies_to_kinds") or []), b.get("provenance"), "orario")
    for b in ts.get("supplement_bands") or []:
        per = _periodo((b.get("rate") or {}).get("periods"))
        if per:
            add(f"Maggiorazione · {b.get('description', b.get('code'))}", f"Maggiorazione {_pct(per['value'])} ({b.get('description', '')}).",
                "maggiorazione notturno festivo domenica turni lavoro ordinario " + " ".join(b.get("applies_to_kinds") or []),
                b.get("provenance"), "orario")
    lr = w.get("leave_rules") or {}
    if lr:
        tiers = "; ".join(f"da {t['service_months_min'] // 12} anni: {t['annual_days']} giorni" for t in lr.get("entitlement_tiers") or [])
        add("Ferie annue", f"Ferie: {lr.get('default_annual_days')} giorni l'anno" + (f" ({tiers})." if tiers else "."),
            "ferie giorni di ferie vacanze riposo annuale maturazione", lr.get("provenance"), "assenze")
        for pm in lr.get("permits") or []:
            ore = ", ".join(str(h.get("hours")) for h in pm.get("annual_hours") or [])
            add(f"Permessi retribuiti · {pm.get('bucket', '').upper()}", f"Permessi {pm.get('bucket', '').upper()}: {ore} ore l'anno"
                + (" (comprese le ex festività)" if pm.get("includes_ex_festivita") else "") + ".",
                "permessi rol ex festività par riduzione orario ore permesso retribuito", pm.get("provenance"), "assenze")
    sk = w.get("sickness_rules") or {}
    cum = sk.get("cumulation") or {}
    if cum.get("bands"):
        def fascia(b):
            t = (f"da {b['seniority_months_from'] // 12} anni di anzianità: comporto {b['comporto_days']} giorni, "
                 f"retribuzione intera per {b['full_pay_days']} giorni")
            for st in b.get("steps") or []:
                t += f", dal {st['day_from']}° al {st['day_until']}° giorno al {_pct(st['integration_rate'])}"
            return t
        txt = "; ".join(fascia(b) for b in cum["bands"])
        rid = cum.get("reduced_integration_rate")
        add("Malattia: comporto e integrazione", f"Conservazione del posto e trattamento: {txt}."
            + (f" Poi integrazione all'{_pct(rid)}." if rid and float(rid) > 0 else ""),
            "malattia comporto conservazione del posto integrazione indennità carenza assenza per malattia",
            sk.get("provenance"), "assenze")
    nt = w.get("notice") or {}
    if nt.get("bands"):
        txt = "; ".join(f"livelli {', '.join(b['levels'])} fino a {b['up_to_months'] // 12 if b.get('up_to_months') else 'oltre'} anni: "
                        f"{b['months']} mesi" for b in nt["bands"][:9] if b.get("months") is not None)
        add("Preavviso di licenziamento e dimissioni", f"Preavviso: {txt}.",
            "preavviso licenziamento dimissioni cessazione recesso indennità sostitutiva", nt.get("provenance"), "cessazione")
    for f in p.get("employer_funds") or []:
        rate = _periodo((f.get("rate") or {}).get("periods"))
        add(f"Previdenza complementare · {f.get('code')}", f"{f.get('description', '')}"
            + (f" Contributo del datore {_pct(rate['value'])}." if rate else ""),
            "fondo pensione previdenza complementare contributo datore cometa fonte priamo", f.get("provenance"), "fondi")
    for f in p.get("health_funds") or []:
        add(f"Assistenza sanitaria · {f.get('code')}", f.get("description", ""),
            "fondo sanitario assistenza sanitaria integrativa metasalute est sanilog", f.get("provenance"), "fondi")
    for a in d.get("apprenticeship") or []:
        perc = [f"{_pct(x.get('value'))}" for x in (a.get("periods") or []) if x.get("value")]
        add(f"Apprendistato · {a.get('name', '').replace('_', ' ')}", f"Percorso {a.get('name', '').replace('_', ' ')}"
            + (f": retribuzione in percentuale del livello di destinazione ({', '.join(perc)})." if perc else "."),
            "apprendistato apprendista apprendisti percentuale retribuzione formazione", a.get("provenance"), "contratti")
    return out


SINONIMI = {"straordinari": "straordinario", "ore": "ore", "notte": "notturno", "domenicale": "domenica",
            "licenziato": "licenziamento", "dimettersi": "dimissioni", "malato": "malattia", "stipendio": "minimo",
            "paga": "minimo", "vacanze": "ferie", "pensione": "previdenza", "anzianita": "anzianità", "trasferte": "trasferta"}
STOP = set("il lo la i gli le un una di a da in con su per tra fra e o che come quanto quanti quante qual quale quali è sono "
           "del della dei delle al alla ai agli nel nella mi si ci ne non più cosa spetta spettano devo".split())


def _tok(testo):
    parole = re.findall(r"[a-zàèéìòù0-9]+", (testo or "").lower())
    return [SINONIMI.get(p, p) for p in parole if p not in STOP and len(p) > 1]


def cerca(domanda, cid=None, n=3):
    """Ricerca BM25 sulle schede (titolo, testo, parole chiave). Restituisce [(punteggio, scheda)]."""
    insieme = [s for c in ([cid] if cid else CONTRATTI) for s in schede(c)]
    docs = [_tok(s["titolo"] + " " + s["testo"] + " " + s["chiavi"]) for s in insieme]
    q = _tok(domanda)
    if not q or not docs:
        return []
    N = len(docs)
    avg = sum(len(x) for x in docs) / N
    df = Counter(t for doc in docs for t in set(doc))
    risultati = []
    for s, doc in zip(insieme, docs):
        tf = Counter(doc)
        punti = 0.0
        for t in q:
            if t in tf:
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                punti += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(doc) / avg))
        if punti > 0:
            risultati.append((round(punti, 2), s))
    risultati.sort(key=lambda x: -x[0])
    return risultati[:n]


# Domande dell'esercitazione: per ciascuna il tema della scheda che deve uscire per prima
DOMANDE = [
    ("Quanto si paga lo straordinario nelle prime due ore nel metalmeccanico?", "metalmeccanico-federmeccanica", "Straordinario"),
    ("Ogni quanto matura uno scatto di anzianità nel metalmeccanico e quanti se ne possono avere?", "metalmeccanico-federmeccanica", "Scatti"),
    ("Quanti giorni di ferie spettano a un commesso del commercio?", "commercio-confcommercio", "Ferie"),
    ("Qual è la paga base del 4° livello nel commercio?", "commercio-confcommercio", "Minimi"),
    ("Quanto dura il comporto di malattia per un dipendente della logistica?", "logistica-trasporto-confetra", "Malattia"),
    ("Qual è il divisore orario della logistica?", "logistica-trasporto-confetra", "Divisore"),
    ("Quante mensilità prevede il CCNL del commercio?", "commercio-confcommercio", "Mensilità"),
    ("Quanti mesi di preavviso per un impiegato B2 metalmeccanico con 8 anni di anzianità?", "metalmeccanico-federmeccanica", "Preavviso"),
    ("Quante ore di ROL ed ex festività ha un operaio metalmeccanico?", "metalmeccanico-federmeccanica", "Permessi"),
    ("Qual è il fondo di previdenza complementare dei metalmeccanici e quanto versa l'azienda?", "metalmeccanico-federmeccanica", "Previdenza"),
]


# ------------------------------------------------------------------------------------------- seconda opinione
TRACCIA_APPRENDISTA = "professionalizzante_36"


def busta_engine(livello, inizio, tipo, part_time=100.0, fine=None, cid="metalmeccanico-federmeccanica", headcount=8):
    """Busta di novembre 2026 secondo ccnl-engine. Restituisce le voci principali o un errore leggibile."""
    from decimal import Decimal

    from ccnl_engine import CompetenceYearPlan, EmployerProfile, Employment, Headcount, PayrollEngine
    from ccnl_engine.inputs import Apprentice, EmploymentPeriod, FixedTerm, Permanent, SeniorityFact, SenioritySource, WeeklyHours

    if tipo == "apprendistato":
        mesi = max(0, (DATA_RIF.year - inizio.year) * 12 + DATA_RIF.month - inizio.month)
        ct = Apprentice(months_elapsed=mesi, track=TRACCIA_APPRENDISTA)
    elif tipo == "determinato":
        ct = FixedTerm(renewals=0)
    else:
        ct = Permanent()
    mesi_anz = max(0, (date(2026, 1, 1).year - inizio.year) * 12 + 1 - inizio.month)
    kw = {}
    if part_time and part_time < 100:
        kw["weekly_hours"] = WeeklyHours(Decimal(str(40 * part_time / 100)))
        kw["full_time_weekly_hours"] = WeeklyHours(Decimal("40"))
    emp = Employment(ccnl_id=cid, level_code=livello, contract_type=ct,
                     employment_period=EmploymentPeriod(started_on=inizio, ended_on=fine),
                     seniority=SeniorityFact(months=mesi_anz, as_of=date(2026, 1, 1), source=SenioritySource.EMPLOYER_RECORDS,
                                             earned=None, promotion=None) if tipo != "apprendistato" else None, **kw)
    y = _engine().calculate_competence_year(CompetenceYearPlan(year=2026, employment=emp,
                                                               employer=EmployerProfile(headcount=Headcount(headcount))))
    nov = [r for r in y.period_results if r.period_id.month == 11]
    if not nov:
        raise ValueError("novembre 2026 non calcolato")
    r = nov[0]
    voci = {}
    for it in r.pay_items:
        voci[it.kind] = voci.get(it.kind, 0) + float(it.amount)
    base = sum(float(it.amount) for it in r.pay_items if it.kind == "base_salary_earning")
    scatti = sum(float(it.amount) for it in r.pay_items if it.kind == "seniority_earning")
    inps_er = sum(float(it.amount) for it in r.pay_items if it.item_id.startswith("inps_employer"))
    tfr = sum(float(it.amount) for it in r.pay_items if it.kind == "tfr_accrual_item")
    return {"lordo": float(r.period_gross), "netto": float(r.period_net), "costo": float(r.period_employer_cost),
            "minimo": round(base, 2), "scatti": round(scatti, 2), "inps_azienda": round(inps_er, 2), "tfr": round(tfr, 2),
            "aliquota_inps": round(inps_er / float(r.period_gross) * 100, 2) if float(r.period_gross) else 0.0,
            "dati_mancanti": sorted({traduci_dato(b.feature) for b in y.blockers if b.feature}), "pagabile": bool(y.is_payable)}


@lru_cache(maxsize=1)
def _engine():
    from ccnl_engine import PayrollEngine
    return PayrollEngine.bundled()


CAUSE = ["minimi indicativi del gestionale", "scatti di anzianità non aggiornati", "aliquota contributiva diversa",
         "percentuale dell'apprendista", "part-time", "nessuna differenza rilevante"]


def confronto(dipendenti):
    """dipendenti: lista di dict {matricola, nome, livello, inizio, fine, tipo, part_time, minimo, scatti_n, scatto, superminimo}
    con i dati di MasterPayroll. Per ognuno: valori MasterPayroll, valori ccnl-engine e differenze."""
    out = []
    for d in dipendenti:
        mp_min = round(d["minimo"] * d["part_time"] / 100, 2)
        mp_sc = round(d["scatti_n"] * d["scatto"] * d["part_time"] / 100, 2)
        riga = {**d, "mp_minimo": mp_min, "mp_scatti": mp_sc, "mp_aliquota": 29.58}
        try:
            e = busta_engine(d["livello"], d["inizio"], d["tipo"], d["part_time"], d.get("fine"))
            riga.update({"en": e, "diff_minimo": round(mp_min - e["minimo"], 2), "diff_scatti": round(mp_sc - e["scatti"], 2),
                         "errore": None})
        except Exception as ex:  # un caso che il motore non copre: lo si dice, non si inventa
            riga.update({"en": None, "errore": "Il motore non calcola questo caso (dettaglio tecnico: " + str(ex)[:160] + ")"})
        out.append(riga)
    return out


# ------------------------------------------------------------------------------------------- esercitazione L1
def _ot(cid, i=0):
    b = (dati(cid)["work_rules"].get("time_supplements") or {}).get("overtime_bands") or []
    per = _periodo((b[i].get("rate") or {}).get("periods")) if len(b) > i else None
    return _pct(per["value"]) if per else None


def _par(cid, chiave):
    per = _periodo((dati(cid)["parameters"].get(chiave) or {}).get("periods"))
    return str(per["value"]) if per else None


def _scatti(cid):
    si = dati(cid)["parameters"].get("seniority_increments") or {}
    return f"ogni {si['cadence_months']} mesi, massimo {si['maximum_count']}" if si.get("cadence_months") else None


def _ferie(cid):
    lr = dati(cid)["work_rules"].get("leave_rules") or {}
    return f"{lr['default_annual_days']} giorni" if lr.get("default_annual_days") else None


def _minimo(cid, livello):
    for lv in dati(cid)["levels"]:
        if lv["code"] == livello:
            per = _periodo((lv.get("base_salary") or {}).get("periods"))
            return _eur(per["value"]) if per else None
    return None


def _comporto(cid):
    bands = ((dati(cid)["work_rules"].get("sickness_rules") or {}).get("cumulation") or {}).get("bands") or []
    return f"{bands[0]['comporto_days']} giorni" if bands else None


def _rol(cid):
    for pm in (dati(cid)["work_rules"].get("leave_rules") or {}).get("permits") or []:
        if pm.get("bucket") == "rol":
            return f"{pm['annual_hours'][0]['hours']} ore"
    return None


def _fondo(cid):
    for f in dati(cid)["parameters"].get("employer_funds") or []:
        per = _periodo((f.get("rate") or {}).get("periods"))
        return f"{f['code']}, {_pct(per['value'])}" if per else f["code"]
    return None


def _preavviso_b2(cid):
    for b in (dati(cid)["work_rules"].get("notice") or {}).get("bands") or []:
        if "B2" in b.get("levels", []) and "dismissal" in b.get("causes", []) and (b.get("up_to_months") or 10 ** 6) >= 96:
            return f"{b['months']} mesi"
    return None


MET, COM, LOG = "metalmeccanico-federmeccanica", "commercio-confcommercio", "logistica-trasporto-confetra"
QUIZ = [
    ("Metalmeccanico: maggiorazione delle prime due ore di straordinario feriale.", MET, lambda c: _ot(c, 0), ["10%", "50%"]),
    ("Metalmeccanico: cadenza e numero massimo degli scatti di anzianità.", MET, _scatti, ["ogni 36 mesi, massimo 10", "ogni 12 mesi, massimo 8"]),
    ("Commercio: giorni di ferie l'anno.", COM, _ferie, ["20 giorni", "22 giorni"]),
    ("Commercio: paga base mensile del 4° livello a novembre 2026 (senza contingenza ed EDR).", COM, lambda c: _minimo(c, "4"), ["1.850,00 €", "1.522,73 €"]),
    ("Logistica: comporto di malattia nella prima fascia di anzianità.", LOG, _comporto, ["183 giorni", "180 giorni"]),
    ("Logistica: divisore orario.", LOG, lambda c: _par(c, "hourly_divisor"), ["173", "160"]),
    ("Commercio: mensilità annue.", COM, lambda c: _par(c, "additional_months"), ["13", "15"]),
    ("Metalmeccanico: preavviso di licenziamento di un B2 con 8 anni di anzianità.", MET, _preavviso_b2, ["2 mesi", "4 mesi"]),
    ("Metalmeccanico: ore annue di ROL ed ex festività.", MET, _rol, ["56 ore", "72 ore"]),
    ("Metalmeccanico: fondo di previdenza complementare e contributo del datore.", MET, _fondo, ["FONTE, 1,55%", "PRIAMO, 1%"]),
]


def quiz_ccnl():
    """Per ogni domanda: testo, contratto, risposta giusta letta dalle schede e tre opzioni (giusta + due distrattori presi
    dagli altri contratti o dalle varianti)."""
    import random
    out = []
    for i, (testo, cid, f, varianti) in enumerate(QUIZ):
        giusta = f(cid)
        opz = [giusta]
        for altro in [MET, COM, LOG] + [None] * len(varianti):
            v = f(altro) if altro else None
            if v and v not in opz:
                opz.append(v)
        for v in varianti:
            if v not in opz:
                opz.append(v)
        opz = opz[:3]
        random.Random(f"quiz-ccnl-{i}").shuffle(opz)
        out.append({"n": i, "testo": testo, "ccnl": cid, "giusta": giusta, "opzioni": opz})
    return out


def causa_principale(riga):
    """Soluzione dell'esercitazione L5: la causa che spiega la differenza più grande."""
    if riga.get("tipo") == "apprendistato":
        return "percentuale dell'apprendista"
    if not riga.get("en"):
        return None
    dm, ds = abs(riga["diff_minimo"]), abs(riga["diff_scatti"])
    if max(dm, ds) <= 1:
        return "nessuna differenza rilevante"
    return "scatti di anzianità non aggiornati" if ds > dm else "minimi indicativi del gestionale"
