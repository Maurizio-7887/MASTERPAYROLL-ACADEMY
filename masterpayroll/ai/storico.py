"""Storico del costo del personale di Ferro & Transenne, ottobre 2024 - settembre 2026 (24 mesi).

È l'esportazione mensile del gestionale paghe precedente: una riga per dipendente e mese. I numeri sono sintetici ma
coerenti (minimi e scatti delle tabelle del corso, straordinari al 25%, contributi c/azienda, INAIL, TFR) e sono uguali in
ogni ambiente. Dentro ci sono SETTE anomalie nascoste, elencate in ANOMALIE (riservate al docente): l'esercitazione chiede
di trovarle. Le variazioni legittime (trasferte di Esposito a settembre 2026, malattie, ferie d'agosto) restano: non ogni
scostamento è un errore.
"""
import random
from datetime import date, timedelta

from ..hr_service import italian_holidays

INIZIO = (2024, 10)
MESI_STORICO = 24
ALIQ_INPS = {"operaio": 0.2958, "impiegato": 0.2958, "quadro": 0.2958, "apprendista": 0.1161}  # come la regola INPS_DITTA
INAIL = 0.025
TRASFERTA_GIORNO = 46.48
SOGLIA_RIMBORSI = 500.0

# matricola, cognome, nome, reparto, qualifica, livello, minimo, scatto unitario, scatti, superminimo, part-time %,
# assunzione, fine, straordinari tipici (min, max), rimborsi tipici (min, max)
ANAGRAFICA = [
    ("0001", "Bianchi", "Marco", "Taglio", "operaio", "C2", 2060.0, 25.5, 2, 0, 100, date(2018, 4, 3), None, (6, 14), (0, 0)),
    ("0002", "Rossi", "Laura", "Amministrazione", "impiegato", "B2", 2410.0, 32.5, 3, 150, 100, date(2019, 1, 1), None, (0, 3), (60, 150)),
    ("0003", "Verdi", "Luca", "Piega", "operaio", "C1", 2000.0, 24.5, 1, 0, 100, date(2021, 2, 15), None, (4, 12), (0, 0)),
    ("0004", "Esposito", "Giuseppe", "Saldatura", "operaio", "C3", 2110.0, 27.0, 4, 80, 100, date(2009, 1, 12), None, (8, 16), (0, 40)),
    ("0005", "Ferri", "Anna", "Commerciale", "impiegato", "C3", 2110.0, 27.0, 0, 0, 50, date(2020, 10, 1), None, (0, 0), (20, 90)),
    ("0006", "Conti", "Davide", "Saldatura", "apprendista", "D2", 1950.0, 23.5, 0, 0, 100, date(2025, 3, 3), date(2028, 3, 2), (2, 8), (0, 0)),
    ("0007", "Galli", "Sara", "Direzione", "quadro", "A1", 2770.0, 38.0, 5, 1900, 100, date(2015, 5, 4), None, (0, 0), (100, 260)),
    ("0008", "Moretti", "Paolo", "Packaging", "operaio", "D2", 1950.0, 23.5, 0, 0, 100, date(2026, 6, 1), date(2027, 5, 31), (2, 10), (0, 0)),
]
APPRENDISTA_PERC = 0.85   # retribuzione dell'apprendista: 85% del minimo del livello di destinazione (didattica)

ANOMALIE = [
    {"id": 1, "mese": "2026-09", "matricola": "0001", "tipo": "straordinari",
     "descrizione": "Straordinari quasi triplicati (34 ore contro una media di 10): ore inserite due volte dal foglio presenze.",
     "metodo": "statistica (z-score robusto) e Isolation Forest"},
    {"id": 2, "mese": "2026-08", "matricola": "0003", "tipo": "scatti",
     "descrizione": "Importo degli scatti di anzianità azzerato: lo scatto maturato non può sparire.",
     "metodo": "regola: gli scatti non diminuiscono"},
    {"id": 3, "mese": "2026-06", "matricola": "0005", "tipo": "part-time",
     "descrizione": "Part-time al 50% pagato a tempo pieno: ore ordinarie e minimo raddoppiati.",
     "metodo": "regola: ore pagate oltre la percentuale di part-time"},
    {"id": 4, "mese": "2026-03", "matricola": "0002", "tipo": "rimborsi",
     "descrizione": "Rimborso chilometrico di 1.450 € contro i soliti 60-150 €: fuori soglia e senza pezze giustificative.",
     "metodo": "regola sulla soglia e statistica"},
    {"id": 5, "mese": "2026-09", "matricola": "0006", "tipo": "contributi",
     "descrizione": "Apprendista con i contributi c/azienda all'aliquota piena (29,58%) invece di quella ridotta: è la causa "
                    "principale dell'aumento del costo del reparto Saldatura a parità di ore.",
     "metodo": "regola sull'aliquota per qualifica e scomposizione del costo di reparto"},
    {"id": 6, "mese": "2026-04", "matricola": "0008", "tipo": "anagrafica",
     "descrizione": "Busta pagata ad aprile a un dipendente assunto il 1° giugno 2026.",
     "metodo": "regola: busta fuori dal periodo del contratto"},
    {"id": 7, "mese": "2026-02", "matricola": "0007", "tipo": "duplicato",
     "descrizione": "Busta di febbraio della responsabile di produzione elaborata due volte.",
     "metodo": "regola: un dipendente, un mese, una busta"},
]
TIPI = ["straordinari", "scatti", "part-time", "rimborsi", "contributi", "anagrafica", "duplicato", "legittima"]


def mesi():
    a, m = INIZIO
    out = []
    for _ in range(MESI_STORICO):
        out.append((a, m))
        m += 1
        if m == 13:
            a, m = a + 1, 1
    return out


def ore_teoriche(anno, mese):
    fest = {d for d, _ in italian_holidays(anno)}
    d = date(anno, mese, 1)
    n = 0
    while d.month == mese:
        if d.weekday() < 5 and d not in fest:
            n += 1
        d += timedelta(days=1)
    return n * 8.0


def _attivo(a, anno, mese):
    inizio, fine = a[11], a[12]
    primo = date(anno, mese, 1)
    ultimo = (date(anno + mese // 12, mese % 12 + 1, 1) - timedelta(days=1))
    return inizio <= ultimo and (fine is None or fine >= primo)


def _riga(a, anno, mese, rnd, **forza):
    matr, cogn, nome, rep, qual, liv, minimo, scatto, n_sc, supermin, pt, *_ = a
    str_min, str_max = a[13]
    rimb_min, rimb_max = a[14]
    teor = ore_teoriche(anno, mese)
    frazione = pt / 100.0
    ore_ord = forza.get("ore_ord", round(teor * frazione, 1))
    base = minimo * (APPRENDISTA_PERC if qual == "apprendista" else 1.0)
    minimo_m = forza.get("minimo", round(base * frazione, 2))
    scatti_imp = forza.get("scatti_imp", round(scatto * n_sc * frazione, 2))
    super_m = round(supermin * frazione, 2)
    ore_mal = 0.0
    if rnd.random() < 0.09:
        ore_mal = 8.0 * rnd.randint(1, 4)
    ferie = 8.0 * (rnd.randint(8, 12) if mese == 8 else (rnd.randint(2, 5) if mese == 12 else rnd.randint(0, 2)))
    ore_lav = max(0.0, round(ore_ord - ore_mal - ferie * frazione, 1))
    fattore_str = 0.35 if mese == 8 else 1.0
    ore_str = forza.get("ore_str", float(round(rnd.randint(str_min, str_max) * fattore_str)) if str_max else 0.0)
    paga_oraria = (base + scatto * n_sc + supermin) / 173.0
    str_imp = round(ore_str * paga_oraria * 1.25, 2)
    gg_trasf = forza.get("gg_trasf", rnd.choice([0, 0, 0, 1, 2]) if matr == "0004" else 0)
    trasf = round(gg_trasf * TRASFERTA_GIORNO, 2)
    rimborsi = forza.get("rimborsi", float(rnd.randint(rimb_min, rimb_max)) if rimb_max else 0.0)
    lordo = round(minimo_m + scatti_imp + super_m + str_imp, 2)       # imponibile: trasferte forfettarie e rimborsi esenti
    aliq = forza.get("aliquota", ALIQ_INPS[qual])
    contrib = round(lordo * aliq, 2)
    inail = round(lordo * INAIL, 2)
    tfr = round(lordo / 13.5, 2)
    costo = round(lordo + trasf + rimborsi + contrib + inail + tfr, 2)
    return {"mese": f"{anno}-{mese:02d}", "anno": anno, "m": mese, "matricola": matr, "dipendente": f"{cogn} {nome}",
            "reparto": rep, "qualifica": qual, "livello": liv, "part_time": pt, "ore_teoriche": teor,
            "ore_ordinarie": ore_ord, "ore_lavorate": ore_lav, "ore_malattia": ore_mal, "ore_straordinario": ore_str,
            "minimo": minimo_m, "scatti": scatti_imp, "superminimo": super_m, "straordinari": str_imp,
            "giorni_trasferta": gg_trasf, "trasferte": trasf, "rimborsi": rimborsi, "lordo": lordo,
            "aliquota_inps": aliq, "contributi_azienda": contrib, "inail": inail, "tfr": tfr, "costo": costo}


def genera():
    """Le righe dello storico, in ordine di mese e matricola (sempre uguali: seed fisso)."""
    rnd = random.Random("ferro-transenne-storico")
    righe = []
    for anno, mese in mesi():
        chiave = f"{anno}-{mese:02d}"
        for a in ANAGRAFICA:
            matr = a[0]
            forza = {}
            if chiave == "2026-09" and matr == "0001":
                forza["ore_str"] = 34.0
            if chiave == "2026-08" and matr == "0003":
                forza["scatti_imp"] = 0.0
            if chiave == "2026-06" and matr == "0005":
                forza["ore_ord"] = ore_teoriche(anno, mese)
                forza["minimo"] = a[6]
                forza["scatti_imp"] = 0.0
            if chiave == "2026-03" and matr == "0002":
                forza["rimborsi"] = 1450.0
            if chiave == "2026-09" and matr == "0006":
                forza["aliquota"] = ALIQ_INPS["operaio"]
            if chiave == "2026-09" and matr == "0004":
                forza["gg_trasf"] = 6
            if chiave == "2026-04" and matr == "0008":
                righe.append(_riga(a, anno, mese, rnd, ore_str=0.0))      # busta fantasma
                continue
            if not _attivo(a, anno, mese):
                rnd.random()
                continue
            r = _riga(a, anno, mese, rnd, **forza)
            righe.append(r)
            if chiave == "2026-02" and matr == "0007":
                righe.append(dict(r))                                       # busta doppia
    for i, r in enumerate(righe, 1):
        r["riga"] = i
    return righe


STORICO = genera()


def anagrafica_per_matricola():
    return {a[0]: {"matricola": a[0], "dipendente": f"{a[1]} {a[2]}", "reparto": a[3], "qualifica": a[4], "livello": a[5],
                   "part_time": a[10], "assunzione": a[11], "fine": a[12]} for a in ANAGRAFICA}


def righe_anomale():
    """Indici (riga) delle righe con le anomalie, per la correzione."""
    out = {}
    for an in ANOMALIE:
        rr = [r for r in STORICO if r["mese"] == an["mese"] and r["matricola"] == an["matricola"]]
        out[an["id"]] = [r["riga"] for r in (rr[1:] if an["tipo"] == "duplicato" else rr)]
    return out


COLONNE_CSV = ["riga", "mese", "matricola", "dipendente", "reparto", "qualifica", "livello", "part_time", "ore_teoriche",
               "ore_ordinarie", "ore_lavorate", "ore_malattia", "ore_straordinario", "minimo", "scatti", "superminimo",
               "straordinari", "giorni_trasferta", "trasferte", "rimborsi", "lordo", "aliquota_inps",
               "contributi_azienda", "inail", "tfr", "costo"]
