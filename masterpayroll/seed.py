"""Dati dimostrativi: azienda fittizia Ferro & Transenne Srl (metalmeccanica).

Ogni ambiente (allievo o docente) riceve una copia identica di questi dati e
può ripristinarla in qualsiasi momento. TUTTI I DATI SONO INVENTATI e i
valori economici sono indicativi a scopo didattico.
"""
from datetime import date

from .fiscale import SCAGLIONI_IRPEF_DEFAULT
from .models import (now, Categoria, Cedolino, CedolinoInput, Contratto, Dipendente,
                     Elaborazione, Esercitazione, Livello, Parametro, Regola,
                     ScaglioneIrpef, Struttura, Workspace, db)

PARAMETRI = [
    ("INPS_DIP", "Aliquota IVS a carico dipendente", 9.19, "%"),
    ("INPS_AGG", "Contributo aggiuntivo oltre la 1ª fascia pensionabile", 1.0, "%"),
    ("MASSIMALE_1FASCIA_MESE", "Limite mensile 1ª fascia pensionabile", 4621.0, "€"),
    ("INPS_DITTA", "Aliquota contributiva a carico azienda (industria)", 29.58, "%"),
    ("INAIL_TASSO", "Tasso INAIL della PAT (per mille)", 25.0, "‰"),
    ("TFR_DIVISORE", "Divisore annuo del TFR (art. 2120 c.c.)", 13.5, ""),
    ("CONTR_TFR_05", "Contributo 0,50% che riduce la quota TFR", 0.50, "%"),
    ("MAGG_STR_25", "Maggiorazione straordinario feriale", 25.0, "%"),
    ("MAGG_STR_50", "Maggiorazione straordinario festivo/notturno", 50.0, "%"),
    ("MENSILITA", "Numero mensilità annue (12 + tredicesima)", 13.0, ""),
    ("TRATT_INTEGRATIVO", "Trattamento integrativo annuo massimo", 1200.0, "€"),
    ("FERIE_ORE_ANNUE", "Ore di ferie maturate in un anno", 160.0, "ore"),
    ("ROL_ORE_ANNUE", "Ore di permesso (ROL) maturate in un anno", 104.0, "ore"),
]

CATEGORIE = [
    ("BASE", "Retribuzione base", "competenza", 10),
    ("COMP", "Altre competenze imponibili", "competenza", 20),
    ("RIDUZ", "Riduzioni per assenze", "trattenuta", 25),
    ("LORDO", "Lordo imponibile", "info", 30),
    ("IMP", "Imponibili e basi di calcolo", "info", 40),
    ("PREV", "Trattenute previdenziali", "trattenuta", 50),
    ("FISC", "Trattenute fiscali", "trattenuta", 60),
    ("ESENTE", "Somme non imponibili", "competenza", 70),
    ("ALTRE", "Altre trattenute", "trattenuta", 80),
    ("NETTO", "Netto in busta", "info", 90),
    ("DITTA", "Oneri a carico azienda", "info", 100),
    ("INFO", "Altre informazioni", "info", 110),
]

# Livelli CCNL Metalmeccanica industria (inquadramento 2021). Importi INDICATIVI.
LIVELLI = [
    ("D1", "Attività semplici e ripetitive", 1800.0, 21.0),
    ("D2", "Attività semplici con conoscenze di base", 1950.0, 23.5),
    ("C1", "Operaio qualificato", 2000.0, 24.5),
    ("C2", "Operaio specializzato / impiegato d'ordine", 2060.0, 25.5),
    ("C3", "Specializzato con autonomia / impiegato esecutivo", 2110.0, 27.0),
    ("B1", "Impiegato di concetto", 2250.0, 29.5),
    ("B2", "Tecnico / impiegato con autonomia operativa", 2410.0, 32.5),
    ("B3", "Tecnico esperto / capo reparto", 2540.0, 34.5),
    ("A1", "Quadro / responsabile di funzione", 2770.0, 38.0),
]

_ORE_DIV = "categories.BASE / contract.divisore"

# (seq, codice, nome, categoria, condizione, formula, quantità, base, stampa, registro, nota)
REGOLE_COMUNI_PRE = [
    (100, "LORDO", "Totale lordo imponibile", "LORDO", "",
     "categories.BASE + categories.COMP - categories.RIDUZ", "", "", False, "",
     "Somma delle competenze imponibili meno le riduzioni per assenze."),
    (110, "IMP_PREV", "Imponibile previdenziale", "IMP", "",
     "round(rules.LORDO, 0)", "", "", False, "",
     "L'imponibile contributivo si arrotonda all'unità di euro."),
    (120, "INPS_DIP", "Contributo IVS c/dipendente", "PREV", "",
     "rules.IMP_PREV * param.INPS_DIP / 100", "param.INPS_DIP", "rules.IMP_PREV", True, "INPS",
     "Aliquota a carico del lavoratore sull'imponibile previdenziale."),
    (130, "INPS_AGG", "Contributo aggiuntivo 1% (oltre 1ª fascia)", "PREV",
     "rules.IMP_PREV > param.MASSIMALE_1FASCIA_MESE",
     "(rules.IMP_PREV - param.MASSIMALE_1FASCIA_MESE) * param.INPS_AGG / 100",
     "param.INPS_AGG", "rules.IMP_PREV - param.MASSIMALE_1FASCIA_MESE", True, "INPS",
     "Semplificazione didattica: nella realtà il superamento si verifica sul cumulo annuo."),
    (200, "IMP_FISC", "Imponibile fiscale", "IMP", "",
     "rules.LORDO - categories.PREV", "", "", False, "",
     "I contributi a carico del dipendente sono deducibili: si tolgono prima di calcolare l'IRPEF."),
]

REGOLE_DITTA = [
    (600, "INPS_DITTA", "Contributi INPS c/azienda", "DITTA", "",
     "rules.IMP_PREV * param.INPS_DITTA / 100", "param.INPS_DITTA", "rules.IMP_PREV", False, "INPS", ""),
    (610, "INAIL", "Premio INAIL (rateo del mese)", "DITTA", "",
     "rules.IMP_PREV * param.INAIL_TASSO / 1000", "param.INAIL_TASSO", "rules.IMP_PREV", False, "INAIL",
     "Il tasso INAIL è espresso per mille e dipende dal rischio della lavorazione."),
    (620, "TFR", "Quota TFR maturata", "DITTA", "",
     "categories.BASE / param.TFR_DIVISORE", "", "categories.BASE", False, "Fondo TFR",
     "Retribuzione utile / 13,5. Qui si usa solo la retribuzione base: discutere quali voci includere."),
    (630, "TFR_NETTO", "Quota TFR al netto dello 0,50%", "INFO", "",
     "rules.TFR - rules.IMP_PREV * param.CONTR_TFR_05 / 100", "", "", False, "Fondo TFR",
     "Il contributo 0,50% si versa all'INPS e si recupera riducendo il TFR accantonato."),
    (700, "COSTO", "Costo aziendale del mese", "INFO", "",
     "rules.LORDO + inputs.RIMBORSI + categories.DITTA", "", "", False, "",
     "Somme esenti del cuneo e trattamento integrativo NON sono un costo: l'azienda le recupera in F24."),
]

NETTO = (500, "NETTO", "Netto in busta", "NETTO", "",
         "categories.BASE + categories.COMP + categories.ESENTE - categories.RIDUZ"
         " - categories.PREV - categories.FISC - categories.ALTRE", "", "", False, "",
         "Competenze meno trattenute.")

REGOLE_ORDINARIA = [
    (10, "PAGA_BASE", "Minimo contrattuale", "BASE", "",
     "contract.minimo * contract.part_time / 100", "", "", True, "",
     "Minimo tabellare del livello CCNL, riproporzionato se part-time."),
    (20, "SUPERMIN", "Superminimo individuale", "BASE", "contract.superminimo > 0",
     "contract.superminimo * contract.part_time / 100", "", "", True, "",
     "Importo concordato in più rispetto al minimo del CCNL."),
    (30, "SCATTI", "Scatti di anzianità", "BASE", "contract.scatti_n > 0",
     "contract.scatti_n * contract.scatto_importo * contract.part_time / 100",
     "contract.scatti_n", "contract.scatto_importo * contract.part_time / 100", True, "",
     "Numero di scatti maturati per l'importo dello scatto del livello."),
    (40, "PAGA_ORARIA", "Paga oraria (retribuzione / divisore)", "INFO", "",
     _ORE_DIV, "", "categories.BASE", False, "",
     "Il divisore orario del CCNL metalmeccanico è 173."),
    (50, "STR25", "Straordinario feriale 25%", "COMP", "inputs.STR25 > 0",
     f"inputs.STR25 * {_ORE_DIV} * (1 + param.MAGG_STR_25 / 100)",
     "inputs.STR25", f"{_ORE_DIV} * (1 + param.MAGG_STR_25 / 100)", True, "", ""),
    (60, "STR50", "Straordinario festivo/notturno 50%", "COMP", "inputs.STR50 > 0",
     f"inputs.STR50 * {_ORE_DIV} * (1 + param.MAGG_STR_50 / 100)",
     "inputs.STR50", f"{_ORE_DIV} * (1 + param.MAGG_STR_50 / 100)", True, "", ""),
    (70, "PREMIO", "Premio una tantum", "COMP", "inputs.PREMIO > 0",
     "inputs.PREMIO", "", "", True, "", ""),
    (80, "ASSENZE", "Assenze non retribuite", "RIDUZ", "inputs.ORE_ASS > 0",
     f"inputs.ORE_ASS * {_ORE_DIV}", "inputs.ORE_ASS", _ORE_DIV, True, "",
     "Le ore di assenza non retribuita riducono il lordo."),
    *REGOLE_COMUNI_PRE,
    (210, "REDD_ANNUO", "Reddito annuo presunto", "IMP", "",
     "reddito_presunto_annuo", "", "", False, "",
     "Retribuzione mensile × mensilità, al netto dei contributi: serve per detrazioni e cuneo."),
    (220, "IRPEF_LORDA", "IRPEF lorda (scaglioni rapportati al mese)", "IMP", "",
     "irpef_annua(rules.IMP_FISC * 12) / 12", "", "rules.IMP_FISC", False, "",
     "Applicare gli scaglioni annui a imponibile × 12 e dividere per 12 equivale a usare scaglioni mensili."),
    (230, "DETR_LAV", "Detrazioni per lavoro dipendente", "IMP", "",
     "detrazione_lavoro(rules.REDD_ANNUO) / 12", "", "rules.REDD_ANNUO", False, "",
     "Detrazione annua dell'art. 13 TUIR divisa sui 12 mesi."),
    (240, "DETR_CUNEO", "Ulteriore detrazione (cuneo fiscale)", "IMP", "",
     "cuneo_detrazione(rules.REDD_ANNUO) / 12", "", "rules.REDD_ANNUO", False, "",
     "Spetta per redditi tra 20.000 e 40.000 euro."),
    (250, "IRPEF", "Ritenuta IRPEF", "FISC", "",
     "max(0, rules.IRPEF_LORDA - rules.DETR_LAV - rules.DETR_CUNEO)", "", "rules.IMP_FISC", True,
     "Erario 1001", "IRPEF lorda meno detrazioni, mai negativa."),
    (260, "ADD_REG", "Addizionale regionale (rata)", "FISC", "contract.add_reg_rata > 0",
     "contract.add_reg_rata", "", "", True, "Erario 3802",
     "Si trattiene l'anno dopo, a rate: l'importo della rata è sul contratto."),
    (270, "ADD_COM", "Addizionale comunale (rata)", "FISC", "contract.add_com_rata > 0",
     "contract.add_com_rata", "", "", True, "Erario 3848",
     "Saldo dell'anno precedente (3848); l'acconto ha codice 3847."),
    (300, "TRATT_INT", "Trattamento integrativo", "ESENTE",
     "trattamento_integrativo_spetta(rules.REDD_ANNUO)",
     "param.TRATT_INTEGRATIVO / 12", "", "", True, "Credito 1655",
     "Ex bonus 100 euro: redditi fino a 15.000 euro non incapienti. L'azienda lo recupera in F24."),
    (310, "IND_CUNEO", "Somma esente cuneo fiscale", "ESENTE", "rules.REDD_ANNUO <= 20000",
     "cuneo_indennita(rules.REDD_ANNUO) / 12", "", "rules.REDD_ANNUO", True, "Credito cuneo",
     "Non tassata: 7,1% / 5,3% / 4,8% del reddito secondo la fascia."),
    (320, "RIMBORSI", "Rimborsi spese", "ESENTE", "inputs.RIMBORSI > 0",
     "inputs.RIMBORSI", "", "", True, "",
     "Rimborsi documentati: non sono reddito, non pagano contributi né IRPEF."),
    (400, "ANTICIPO", "Recupero anticipo", "ALTRE", "inputs.ANTICIPO > 0",
     "inputs.ANTICIPO", "", "", True, "", ""),
    NETTO,
    *REGOLE_DITTA,
]

REGOLE_TREDICESIMA = [
    (10, "RATEI", "Mesi maturati", "INFO", "",
     "inputs.MESI_13 if inputs.MESI_13 > 0 else 12", "", "", False, "",
     "Se non indicato, si considera l'anno intero (12 mesi)."),
    (20, "TREDICESIMA", "Tredicesima mensilità", "BASE", "",
     "retribuzione_mensile * rules.RATEI / 12", "rules.RATEI", "retribuzione_mensile / 12", True, "",
     "Retribuzione mensile × mesi maturati / 12."),
    *REGOLE_COMUNI_PRE,
    (250, "IRPEF", "Ritenuta IRPEF (aliquota marginale)", "FISC", "",
     "irpef_annua(reddito_ordinario_annuo + rules.IMP_FISC) - irpef_annua(reddito_ordinario_annuo)",
     "", "rules.IMP_FISC", True, "Erario 1001",
     "Si tassa la tredicesima 'sopra' il reddito dei 12 mesi, senza detrazioni (già godute nei mesi)."),
    NETTO,
    *REGOLE_DITTA,
]

DIPENDENTI = [
    # matr, cognome, nome, CF fittizio, nascita, comune, assunzione, qualifica, mansione, reparto,
    # tipo contratto, livello, superminimo, scatti, part-time, add reg, add com
    ("0001", "Bianchi", "Marco", "BNCMRC85C12C745Q", date(1985, 3, 12), "Città di Castello",
     date(2018, 4, 3), "operaio", "Addetto taglio laser", "Taglio", "indeterminato", "C2", 0, 2, 100, 28.0, 12.0),
    ("0002", "Rossi", "Laura", "RSSLRA79H51G478K", date(1979, 6, 11), "Umbertide",
     date(2012, 9, 1), "impiegato", "Contabilità e paghe", "Amministrazione", "indeterminato", "B2", 150, 3, 100, 45.0, 18.0),
    ("0003", "Verdi", "Luca", "VRDLCU92T08C745M", date(1992, 12, 8), "Città di Castello",
     date(2021, 2, 15), "operaio", "Piegatore pressa", "Piega", "indeterminato", "C1", 0, 1, 100, 25.0, 10.0),
    ("0004", "Esposito", "Giuseppe", "SPSGPP76E20F839T", date(1976, 5, 20), "San Giustino",
     date(2009, 1, 12), "operaio", "Saldatore MIG/TIG", "Saldatura", "indeterminato", "C3", 80, 4, 100, 32.0, 14.0),
    ("0005", "Ferri", "Anna", "FRRNNA88P45D653W", date(1988, 9, 5), "Citerna",
     date(2020, 10, 1), "impiegato", "Ufficio commerciale (part-time)", "Commerciale", "indeterminato", "C3", 0, 0, 50, 0.0, 0.0),
    ("0006", "Conti", "Davide", "CNTDVD04A17C745F", date(2004, 1, 17), "Città di Castello",
     date(2025, 3, 3), "apprendista", "Apprendista saldatore", "Saldatura", "apprendistato", "D2", 0, 0, 100, 0.0, 0.0),
    ("0007", "Galli", "Sara", "GLLSRA80M60H501D", date(1980, 8, 20), "Arezzo",
     date(2015, 5, 4), "impiegato", "Responsabile di produzione", "Direzione", "indeterminato", "A1", 1900, 5, 100, 95.0, 40.0),
    ("0008", "Moretti", "Paolo", "MRTPLA97S03C745R", date(1997, 11, 3), "Città di Castello",
     date(2026, 6, 1), "operaio", "Addetto imballaggio e pallet", "Packaging", "determinato", "D2", 0, 0, 100, 0.0, 0.0),
]

# Variabili del mese d'esempio (settembre 2026), già elaborato e confermato.
ESEMPIO_INPUT = {
    "0001": {"STR25": 8},
    "0003": {"ORE_ASS": 8, "FERIE": 16},
    "0004": {"STR50": 4, "RIMBORSI": 45},
    "0006": {"ANTICIPO": 200},
}

ESERCITAZIONI = [
    ("Conosci l'azienda",
     "Apri Dipendenti e Contratti. Per Bianchi, Rossi e Ferri compila una tabella con livello, minimo, "
     "superminimo, scatti e retribuzione mensile. Perché la retribuzione di Ferri è circa la metà?", "base"),
    ("Elabora il mese di ottobre",
     "Da Elaborazioni crea 'Ottobre 2026 - ordinaria'. Inserisci 10 ore di straordinario al 25% a Bianchi "
     "e 6 ore di assenza non retribuita a Verdi. Calcola tutti i cedolini e annota netto e costo aziendale.", "base"),
    ("Leggi un cedolino riga per riga",
     "Apri il cedolino di settembre di Rossi. Spiega a parole il percorso dal lordo al netto e rifai a mano "
     "il contributo INPS (9,19%) e la ritenuta IRPEF. I tuoi numeri coincidono con il programma?", "medio"),
    ("Part-time e cuneo fiscale",
     "Per Ferri confronta trattamento integrativo e somma esente del cuneo. Poi porta il part-time al 75%, "
     "ricalcola il cedolino di ottobre e spiega cosa cambia e perché.", "medio"),
    ("Compila l'F24",
     "Dal Riepilogo versamenti di settembre ricava gli importi per codice tributo (1001, 3802, 3848), "
     "i crediti da compensare e il totale INPS. Scadenza: il 16 del mese successivo.", "medio"),
    ("Crea una nuova regola",
     "In Strutture e regole aggiungi alla struttura ordinaria la regola IND_TURNO 'Indennità di turno', "
     "categoria COMP, sequenza 75, condizione  employee.reparto == 'Saldatura', formula  50. "
     "Ricalcola Esposito e Conti: come cambiano contributi, IRPEF e netto?", "avanzato"),
    ("La tredicesima",
     "Crea l'elaborazione 'Dicembre 2026 - tredicesima' (struttura tredicesima). Per Moretti indica i mesi "
     "maturati (MESI_13). Perché in proporzione l'IRPEF è più alta che in un mese normale?", "avanzato"),
    ("Verifica critica dei parametri",
     "I valori delle Tabelle sono didattici. Scegli 3 parametri (es. aliquota INPS, scaglioni IRPEF, "
     "1ª fascia pensionabile), cercali su fonti ufficiali (INPS, Agenzia delle Entrate, Gazzetta Ufficiale), "
     "aggiornali se serve e misura l'effetto sul netto di 2 dipendenti.", "avanzato"),
]


def _cat_map(ws_id):
    return {c.codice: c for c in Categoria.query.filter_by(workspace_id=ws_id)}


def _add_struttura(ws_id, codice, nome, tipo, descrizione, regole, cats):
    s = Struttura(workspace_id=ws_id, codice=codice, nome=nome, tipo_cedolino=tipo, descrizione=descrizione)
    db.session.add(s)
    for seq, cod, nome_r, cat, cond, formula, qta, base, stampa, registro, nota in regole:
        s.regole.append(Regola(workspace_id=ws_id, sequenza=seq, codice=cod, nome=nome_r,
                               categoria=cats[cat], condizione=cond, formula=formula,
                               quantita_formula=qta, base_formula=base, stampa=stampa,
                               registro=registro, note=nota))
    return s


def seed_workspace(ws: Workspace, with_example=True):
    ws.ragione_sociale = "Ferro & Transenne Srl"
    ws.partita_iva = "IT00000000000 (fittizia)"
    ws.indirizzo = "Via dell'Industria 12 - 06012 Città di Castello (PG)"
    ws.ccnl = "CCNL Metalmeccanica Industria"
    ws.pat_inail = "00000000/00"
    ws.matricola_inps = "0000000000"
    ws_id = ws.id

    for cod, descr, val, unita in PARAMETRI:
        db.session.add(Parametro(workspace_id=ws_id, codice=cod, descrizione=descr, valore=val, unita=unita))
    for da, a, aliq in SCAGLIONI_IRPEF_DEFAULT:
        db.session.add(ScaglioneIrpef(workspace_id=ws_id, da=da, a=a, aliquota=aliq))
    livelli = {}
    for cod, descr, minimo, scatto in LIVELLI:
        livelli[cod] = Livello(workspace_id=ws_id, codice=cod, descrizione=descr, minimo=minimo,
                               scatto_importo=scatto)
        db.session.add(livelli[cod])
    for cod, nome, tipo, seq in CATEGORIE:
        db.session.add(Categoria(workspace_id=ws_id, codice=cod, nome=nome, tipo=tipo, sequenza=seq))
    db.session.flush()
    cats = _cat_map(ws_id)

    ordinaria = _add_struttura(
        ws_id, "METAL_ORD", "CCNL Metalmeccanico - mensile ordinaria", "ordinaria",
        "Cedolino mensile: retribuzione, straordinari, contributi, IRPEF con detrazioni e cuneo fiscale.",
        REGOLE_ORDINARIA, cats)
    _add_struttura(
        ws_id, "METAL_13", "CCNL Metalmeccanico - tredicesima", "tredicesima",
        "Tredicesima mensilità: ratei, contributi e IRPEF ad aliquota marginale senza detrazioni.",
        REGOLE_TREDICESIMA, cats)
    db.session.flush()

    dip_by_matr = {}
    for (matr, cogn, nome, cf, nascita, comune, assunz, qual, mans, rep,
         tipo, liv, supermin, scatti, pt, add_reg, add_com) in DIPENDENTI:
        d = Dipendente(workspace_id=ws_id, matricola=matr, cognome=cogn, nome=nome, codice_fiscale=cf,
                       data_nascita=nascita, comune_residenza=comune, data_assunzione=assunz,
                       qualifica=qual, mansione=mans, reparto=rep)
        lv = livelli[liv]
        d.contratti.append(Contratto(
            workspace_id=ws_id, tipo=tipo, livello=lv, struttura=ordinaria,
            minimo=lv.minimo, superminimo=supermin, scatti_n=scatti, scatto_importo=lv.scatto_importo,
            part_time=pt, ore_settimanali=40 * pt / 100, divisore_orario=173,
            add_reg_rata=add_reg, add_com_rata=add_com, data_inizio=assunz,
            data_fine=date(2027, 5, 31) if tipo == "determinato" else None))
        db.session.add(d)
        dip_by_matr[matr] = d
    db.session.flush()

    if with_example:
        from .engine import calcola
        el = Elaborazione(workspace_id=ws_id, anno=2026, mese=9, tipo="ordinaria",
                          descrizione="Settembre 2026 - esempio già confermato")
        db.session.add(el)
        for matr, d in dip_by_matr.items():
            c = d.contratto_attivo
            ced = Cedolino(workspace_id=ws_id, elaborazione=el, dipendente=d, contratto=c,
                           struttura=c.struttura, anno=2026, mese=9, tipo="ordinaria",
                           giorni_lavorati=26, ore_lavorate=round(173 * c.part_time / 100, 1))
            for cod, val in ESEMPIO_INPUT.get(matr, {}).items():
                ced.inputs.append(CedolinoInput(codice=cod, valore=val))
            db.session.add(ced)
            db.session.flush()
            calcola(ced, commit=False)
            if ced.stato == "calcolato":
                ced.stato = "confermato"
                ced.confermato_at = now()
    db.session.commit()


def clear_workspace(ws: Workspace):
    """Cancella tutti i dati dell'ambiente (lascia l'ambiente e l'utente)."""
    ws_id = ws.id
    for ced in Cedolino.query.filter_by(workspace_id=ws_id).all():
        db.session.delete(ced)
    db.session.flush()
    for model in (Elaborazione, Contratto, Dipendente, Regola, Struttura, Categoria,
                  Livello, ScaglioneIrpef, Parametro):
        model.query.filter_by(workspace_id=ws_id).delete(synchronize_session=False)
    db.session.commit()


def reset_workspace(ws: Workspace):
    clear_workspace(ws)
    ws.reset_at = now()
    seed_workspace(ws)


def seed_esercitazioni():
    if Esercitazione.query.count():
        return
    for i, (titolo, testo, livello) in enumerate(ESERCITAZIONI, start=1):
        db.session.add(Esercitazione(ordine=i, titolo=titolo, testo=testo, livello=livello))
    db.session.commit()
