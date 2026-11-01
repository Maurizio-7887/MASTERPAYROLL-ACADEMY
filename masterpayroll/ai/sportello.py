"""Sportello HR per i dipendenti: risponde alle domande ricorrenti con i dati del dipendente che chiede (ferie e permessi,
ultima busta, CU) e con le regole aziendali; quello che non sa lo passa all'ufficio paghe.

Regole di comportamento (AI Act art. 50 e GDPR): dice sempre che è un assistente automatico; risponde solo sui dati di chi
chiede, mai su quelli dei colleghi; non prende decisioni sul rapporto di lavoro; registra ogni domanda.
"""
import re
from datetime import date

from .ccnl import _tok

POLICY = [
    ("Rimborso chilometrico", "Con l'auto propria per lavoro si rimborsano 0,40 € al km, con la nota spese mensile e il "
     "percorso indicato. Pedaggi e parcheggi si rimborsano con la ricevuta.", "rimborso chilometrico km auto propria nota spese pedaggio parcheggio"),
    ("Trasferte", "Per le trasferte in Italia spetta l'indennità forfettaria giornaliera (46,48 €, esente). Chi la prende "
     "non può chiedere anche il rimborso di pranzo e cena.", "trasferta trasferte indennità forfettaria pranzo cena vitto"),
    ("Malattia: che cosa fare", "Avvisa il capo reparto prima dell'inizio del turno e comunica all'ufficio paghe il numero di "
     "protocollo del certificato telematico del medico. Durante la malattia rispetta le fasce di reperibilità.",
     "malattia certificato medico protocollo reperibilità fasce visita fiscale assente"),
    ("Richiesta di ferie", "Le ferie si chiedono al capo reparto con almeno 5 giorni lavorativi di anticipo (2 settimane per "
     "periodi oltre 5 giorni); l'ufficio paghe le registra quando sono approvate.", "ferie richiesta chiedere vacanze giorni"),
    ("Bonus e welfare", "I premi e i servizi di welfare dipendono dagli accordi aziendali dell'anno: per l'importo e le "
     "condizioni chiedi all'ufficio paghe. Lo sportello non può promettere importi.", "bonus premio welfare buoni benzina trasporti fringe benefit"),
    ("Orario e straordinari", "L'orario normale è 8-12 e 13-17 dal lunedì al venerdì. Gli straordinari vanno autorizzati dal "
     "capo reparto e compaiono nella busta del mese successivo.", "orario straordinario straordinari autorizzazione turno"),
    ("Cedolino e CU", "Il cedolino si consegna entro il 10 del mese successivo; la Certificazione Unica entro il 16 marzo. "
     "Entrambi si ricevono per email all'indirizzo aziendale.", "cedolino busta paga cu certificazione unica 730"),
]
INTENTI = [("altri", r"\b(collega|colleghi|di bianchi|di rossi|di verdi|di esposito|di ferri|di conti|di galli|di moretti|degli altri)\b"),
           ("ferie", r"\bferie\b.*\b(rimast|resid|quant|ancora|maturat)|\b(rimast|resid|quant).*\bferie\b"),
           ("permessi", r"\b(rol|permess)\w*\b.*\b(rimast|resid|quant)|\b(rimast|resid|quant).*\b(rol|permess)"),
           ("busta", r"\b(netto|busta|cedolino|stipendio)\b.*\b(ultim|mese|quant)|\bquanto\b.*\b(preso|netto)"),
           ("cu", r"\b(cu|certificazione unica)\b")]


def rispondi(domanda, employee, ws_id, oggi=None):
    """(risposta, fonte, inoltro) per la domanda del dipendente."""
    from ..hr_service import contatori_ferie
    from ..models import Parametro, Payslip
    oggi = oggi or date(2026, 11, 30)
    q = (domanda or "").lower()
    for intento, rx in INTENTI:
        if not re.search(rx, q):
            continue
        if intento == "altri":
            if re.search(r"\b(collega|colleghi|degli altri)\b", q) or f"di {employee.last_name.lower()}" not in q:
                return ("Posso rispondere solo sui tuoi dati: le informazioni dei colleghi sono riservate.",
                        "regola di riservatezza", False)
            continue
        if intento in ("ferie", "permessi"):
            par = {p.codice: p.valore for p in Parametro.query.filter_by(workspace_id=ws_id)}
            c = contatori_ferie(employee, oggi.year, oggi, par.get("FERIE_ORE_ANNO", 160.0), par.get("ROL_ORE_ANNO", 104.0))
            if intento == "ferie":
                return (f"Al {oggi:%d/%m/%Y} hai maturato {c['ferie_maturate']:g} ore di ferie, ne hai godute {c['ferie_godute']:g}: "
                        f"te ne restano {c['ferie_residue']:g} ore (circa {c['ferie_residue'] / 8:.1f} giorni).", "Ferie e permessi", False)
            return (f"Permessi ROL ed ex festività: maturati {c['rol_maturati']:g} ore, goduti {c['rol_goduti']:g}, residui "
                    f"{c['rol_residui']:g} ore.", "Ferie e permessi", False)
        if intento == "busta":
            s = (Payslip.query.filter_by(workspace_id=ws_id, employee_id=employee.id, state="done", credit_note=False)
                 .order_by(Payslip.date_from.desc()).first())
            if not s:
                return ("Non trovo ancora buste completate a tuo nome.", "Buste paga", False)
            netto = next((l.total for l in s.line_ids if l.code == "NET"), None)
            return (f"Ultima busta completata: {s.date_from:%m/%Y}" + (f", netto {netto:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if netto is not None else "")
                    + ". Il dettaglio è nel cedolino che ricevi per email.", "Buste paga", False)
        if intento == "cu":
            return ("La Certificazione Unica dei redditi dell'anno si consegna entro il 16 marzo dell'anno dopo, per email. "
                    "Se ti serve quella di un anno passato, la richiesta passa all'ufficio paghe.", "Regole aziendali", True)
    # regole aziendali: ricerca per parole
    qt = set(_tok(domanda))
    migliore, punti = None, 0
    for titolo, testo, chiavi in POLICY:
        p = len(qt & set(_tok(titolo + " " + chiavi)))
        if p > punti:
            migliore, punti = (titolo, testo), p
    if migliore and punti >= 1:
        return (migliore[1], f"Regole aziendali · {migliore[0]}", False)
    return ("Non ho una risposta sicura: ho inoltrato la domanda all'ufficio paghe, che ti risponderà.", "inoltro", True)


DOMANDE_TIPO = [
    ("Quante ferie mi sono rimaste?", "Ferie e permessi"),
    ("Quanti permessi ROL ho ancora?", "Ferie e permessi"),
    ("Quanto ho preso di netto nell'ultima busta?", "Buste paga"),
    ("Mi mandi la CU dell'anno scorso?", "Regole aziendali"),
    ("Quanto mi rimborsate al km se uso la mia auto?", "Regole aziendali · Rimborso chilometrico"),
    ("Sono in trasferta, posso farmi rimborsare il pranzo?", "Regole aziendali · Trasferte"),
    ("Sono malato, cosa devo fare?", "Regole aziendali · Malattia: che cosa fare"),
    ("Quante ferie ha il mio collega Bianchi?", "regola di riservatezza"),
    ("Come funziona il bonus trasporti?", "Regole aziendali · Bonus e welfare"),
    ("Posso portare il cane in ufficio?", "inoltro"),
]
