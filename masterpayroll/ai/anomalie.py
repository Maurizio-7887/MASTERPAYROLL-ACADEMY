"""Controllo delle anomalie prima della chiusura delle paghe, con tre metodi che si completano.

1. Regole: controlli certi scritti dall'ufficio paghe (doppioni, buste fuori contratto, part-time pagato pieno, scatti
   che diminuiscono, rimborsi oltre soglia, aliquota contributiva incoerente con la qualifica).
2. Statistica: z-score robusto (mediana e MAD) di ogni dipendente contro i suoi 12 mesi precedenti.
3. Machine learning: Isolation Forest (scikit-learn) su indicatori normalizzati di ogni riga; segnala le righe «isolate».

E in più la scomposizione della variazione del costo di un reparto tra due mesi: effetto ore, effetto costo orario e le
voci (per dipendente) che spiegano la differenza.
"""
from collections import defaultdict
from statistics import median

from .storico import ALIQ_INPS, SOGLIA_RIMBORSI, anagrafica_per_matricola

METRICHE_Z = [("ore_straordinario", "ore di straordinario", 4.0), ("rimborsi", "rimborsi spese", 150.0),
              ("costo_ora", "costo per ora pagata", 2.0), ("lordo", "lordo imponibile", 150.0)]
SOGLIA_Z = 3.5


def _costo_ora(r):
    ore = r["ore_ordinarie"] + r["ore_straordinario"]
    return r["costo"] / ore if ore else 0.0


def _ultimo_giorno(anno, mese):
    from datetime import date, timedelta
    return date(anno + mese // 12, mese % 12 + 1, 1) - timedelta(days=1)


# ---------------------------------------------------------------------------------------------------- 1. regole
def regole(righe, soglia_rimborsi=SOGLIA_RIMBORSI):
    from datetime import date
    an = anagrafica_per_matricola()
    out = []
    visti = {}
    prec = {}
    for r in sorted(righe, key=lambda x: (x["mese"], x["riga"])):
        a = an.get(r["matricola"])
        k = (r["matricola"], r["mese"])
        if k in visti:
            out.append((r, "duplicato", f"seconda busta dello stesso mese (prima: riga {visti[k]})"))
        visti.setdefault(k, r["riga"])
        if a:
            if a["assunzione"] > _ultimo_giorno(r["anno"], r["m"]) or (a["fine"] and a["fine"] < date(r["anno"], r["m"], 1)):
                out.append((r, "anagrafica", f"busta fuori dal periodo del contratto (dal {a['assunzione']:%d/%m/%Y})"))
            if r["ore_ordinarie"] > r["ore_teoriche"] * a["part_time"] / 100.0 * 1.05:
                out.append((r, "part-time", f"{r['ore_ordinarie']:g} ore pagate su {r['ore_teoriche'] * a['part_time'] / 100:g} "
                                            f"previste dal part-time al {a['part_time']}%"))
            atteso = ALIQ_INPS.get(a["qualifica"])
            if atteso is not None and abs(r["aliquota_inps"] - atteso) > 0.03:
                out.append((r, "contributi", f"aliquota c/azienda {r['aliquota_inps'] * 100:.2f}% invece di "
                                             f"{atteso * 100:.2f}% per la qualifica {a['qualifica']}"))
        p = prec.get(r["matricola"])
        if p is not None and r["scatti"] < p["scatti"] - 0.01 and r["part_time"] == p["part_time"]:
            out.append((r, "scatti", f"scatti da {p['scatti']:.2f} € a {r['scatti']:.2f} €: non possono diminuire"))
        if r["rimborsi"] > soglia_rimborsi:
            out.append((r, "rimborsi", f"rimborsi {r['rimborsi']:.2f} € oltre la soglia di {soglia_rimborsi:.0f} €"))
        if k not in prec or prec[r["matricola"]]["mese"] != r["mese"]:
            prec[r["matricola"]] = r
    return out


# ---------------------------------------------------------------------------------------------------- 2. statistica
def zscore(righe, finestra=12, soglia=SOGLIA_Z):
    """Per ogni riga e metrica: z = 0,6745 × (x − mediana) ÷ MAD dei mesi precedenti dello stesso dipendente.
    Con MAD quasi nullo si usa un minimo per metrica, così un valore sempre uguale non rende «anomalo» un centesimo."""
    storia = defaultdict(list)
    out = []
    for r in sorted(righe, key=lambda x: (x["mese"], x["riga"])):
        hist = storia[r["matricola"]][-finestra:]
        if len(hist) >= 6:
            for campo, etichetta, mad_min in METRICHE_Z:
                x = _costo_ora(r) if campo == "costo_ora" else r[campo]
                valori = [_costo_ora(h) if campo == "costo_ora" else h[campo] for h in hist]
                med = median(valori)
                mad = max(median(abs(v - med) for v in valori), mad_min)
                z = 0.6745 * (x - med) / mad
                if abs(z) >= soglia:
                    out.append((r, campo, round(z, 1), f"{etichetta}: {x:.2f} contro una mediana di {med:.2f} (z = {z:.1f})"))
        storia[r["matricola"]].append(r)
    return out


# ---------------------------------------------------------------------------------------------------- 3. Isolation Forest
def caratteristiche(r):
    teor = r["ore_teoriche"] * r["part_time"] / 100.0 or 1.0
    return [_costo_ora(r), r["ore_straordinario"] / teor * 100, r["rimborsi"] / 100.0, r["aliquota_inps"] * 100,
            r["ore_ordinarie"] / teor * 100, r["scatti"] / 10.0]


def isolation_forest(righe, contaminazione=0.05, seme=42):
    """Punteggio di anomalia per riga (più alto = più isolata). Gli indicatori sono standardizzati per dipendente, così
    il quadro con lo stipendio alto non è «anomalo» solo perché guadagna di più."""
    import numpy as np
    from sklearn.ensemble import IsolationForest

    per_dip = defaultdict(list)
    for r in righe:
        per_dip[r["matricola"]].append(r)
    X, idx = [], []
    for matr, rr in per_dip.items():
        m = np.array([caratteristiche(r) for r in rr], dtype=float)
        mu, sd = m.mean(axis=0), m.std(axis=0)
        sd[sd < 1e-6] = 1.0
        z = (m - mu) / sd
        X.extend(z.tolist())
        idx.extend(rr)
    modello = IsolationForest(n_estimators=300, contamination=contaminazione, random_state=seme)
    modello.fit(X)
    punteggi = -modello.score_samples(X)
    segnalate = modello.predict(X)
    out = [(r, round(float(s), 3), bool(p == -1)) for r, s, p in zip(idx, punteggi, segnalate)]
    out.sort(key=lambda x: -x[1])
    return out


# ---------------------------------------------------------------------------------------------------- insieme
def candidati(righe, contaminazione=0.05):
    """Unione dei tre metodi: una riga per riga dello storico segnalata da almeno un metodo, con i motivi."""
    per_riga = {}

    def voce(r):
        return per_riga.setdefault(r["riga"], {"r": r, "regole": [], "z": [], "if": None})

    for r, tipo, msg in regole(righe):
        voce(r)["regole"].append((tipo, msg))
    for r, campo, z, msg in zscore(righe):
        voce(r)["z"].append(msg)
    for r, s, flag in isolation_forest(righe, contaminazione):
        if flag:
            voce(r)["if"] = s
    out = list(per_riga.values())
    for v in out:
        v["metodi"] = sum(bool(x) for x in (v["regole"], v["z"], v["if"]))
    out.sort(key=lambda v: (-v["metodi"], v["r"]["mese"], v["r"]["matricola"]))
    return out


# ---------------------------------------------------------------------------------------------------- reparto
VOCI = [("retribuzione", "retribuzione (minimo, scatti, superminimo)"), ("straordinari", "straordinari"),
        ("trasferte", "trasferte"), ("rimborsi", "rimborsi spese"), ("contributi_azienda", "contributi c/azienda"),
        ("inail_tfr", "INAIL e TFR")]


def _voci(r):
    return {"retribuzione": r["minimo"] + r["scatti"] + r["superminimo"], "straordinari": r["straordinari"],
            "trasferte": r["trasferte"], "rimborsi": r["rimborsi"], "contributi_azienda": r["contributi_azienda"],
            "inail_tfr": r["inail"] + r["tfr"]}


def reparti(righe):
    return sorted({r["reparto"] for r in righe})


def variazione_reparto(righe, reparto, mese_base, mese_conf):
    """Costo del reparto tra due mesi: effetto ore = (ore conf − ore base) × costo orario base; effetto costo orario =
    (costo orario conf − costo orario base) × ore conf. Le ore sono quelle pagate (ordinarie + straordinarie)."""
    def tot(mese):
        rr = [r for r in righe if r["reparto"] == reparto and r["mese"] == mese]
        costo = sum(r["costo"] for r in rr)
        ore = sum(r["ore_ordinarie"] + r["ore_straordinario"] for r in rr)
        return rr, costo, ore

    rb, cb, hb = tot(mese_base)
    rc, cc, hc = tot(mese_conf)
    cob = cb / hb if hb else 0.0
    coc = cc / hc if hc else 0.0
    cause = defaultdict(float)
    for segno, rr in ((-1, rb), (1, rc)):
        for r in rr:
            for k, v in _voci(r).items():
                cause[(r["dipendente"], k)] += segno * v
    etich = dict(VOCI)
    elenco = sorted(({"dipendente": d, "voce": etich[k], "delta": round(v, 2)} for (d, k), v in cause.items()
                     if abs(v) >= 0.5), key=lambda x: -abs(x["delta"]))
    return {"reparto": reparto, "base": mese_base, "conf": mese_conf, "costo_base": round(cb, 2), "costo_conf": round(cc, 2),
            "ore_base": hb, "ore_conf": hc, "costo_ora_base": round(cob, 2), "costo_ora_conf": round(coc, 2),
            "var_costo_ora_perc": round((coc / cob - 1) * 100, 1) if cob else 0.0,
            "effetto_ore": round((hc - hb) * cob, 2), "effetto_costo_orario": round((coc - cob) * hc, 2),
            "delta": round(cc - cb, 2), "cause": elenco, "prime_tre": elenco[:3]}


# ---------------------------------------------------------------------------------------------------- correzione
def valuta_segnalazioni(segnalate, verita):
    """segnalate: {riga: tipo}; verita: {id anomalia: [righe]} con tipi da ANOMALIE. Una anomalia è trovata se almeno una
    delle sue righe è segnalata con il tipo giusto; le righe segnalate che non sono anomalie sono falsi allarmi."""
    from .storico import ANOMALIE
    tipo_di = {a["id"]: a["tipo"] for a in ANOMALIE}
    righe_vere = {riga: aid for aid, rr in verita.items() for riga in rr}
    trovate, tipo_sbagliato = set(), set()
    falsi = []
    for riga, tipo in segnalate.items():
        if tipo == "legittima":
            continue
        aid = righe_vere.get(riga)
        if aid is None:
            falsi.append(riga)
        elif tipo == tipo_di[aid]:
            trovate.add(aid)
        else:
            tipo_sbagliato.add(aid)
    return {"trovate": sorted(trovate), "tipo_sbagliato": sorted(tipo_sbagliato - trovate), "falsi": sorted(falsi),
            "totale": len(verita), "superata": len(trovate) >= len(verita) - 1 and len(falsi) <= 2}
