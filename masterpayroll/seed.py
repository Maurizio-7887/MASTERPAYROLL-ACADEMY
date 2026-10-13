"""Dati iniziali di ogni ambiente: localizzazione italiana + azienda demo.

Struttura identica ai dati di Odoo (demo/hr_payroll_demo.xml): categorie,
registri contributi, regole con condizioni none/range/python e importi
fix/percentage/code, regole figlie, apporti (hr.rule.input), strutture con
struttura padre. Come in Odoo le TRATTENUTE sono importi NEGATIVI e il netto
è la somma delle categorie.

Azienda fittizia: Ferro & Transenne Srl (metalmeccanica). Tutti i dati sono
inventati; gli importi sono indicativi e servono per imparare.
"""
from datetime import date

from .fiscale import SCAGLIONI_IRPEF_DEFAULT
from .hr_service import italian_holidays
from .models import (WORKSPACE_MODELS, ContributionRegister, Contract, Employee, Esercitazione, Familiare,
                     Leave, LeaveType, Livello, Parametro, Partner, PayrollStructure, PayslipInput,
                     PayslipRun, ResourceCalendar, ResourceCalendarAttendance, ResourceCalendarLeave,
                     RuleInput, SalaryRule, SalaryRuleCategory, ScaglioneIrpef, Workspace, db, now)

PARAMETRI = [
    ("MASSIMALE_1FASCIA_MESE", "Limite mensile della 1ª fascia pensionabile (contributo aggiuntivo 1%)", 4631.0, "€"),
    ("INAIL_TASSO", "Tasso INAIL della PAT (per mille)", 25.0, "‰"),
    ("TFR_DIVISORE", "Divisore annuo del TFR (art. 2120 c.c.)", 13.5, ""),
    ("TRASFERTA_ESENTE", "Indennità di trasferta forfettaria esente in Italia (al giorno)", 46.48, "€"),
]

# (codice, nome, padre, nota)
CATEGORIE = [
    ("BASIC", "Retribuzione base", None, "Minimo, superminimo, scatti: la base della retribuzione."),
    ("ALW", "Indennità e competenze", None, "Altre voci imponibili (positive) o riduzioni (negative)."),
    ("STR", "Straordinari", "ALW", "Figlia di ALW: i suoi importi si sommano anche ad ALW."),
    ("ASS", "Assenze non retribuite", "ALW", "Importi negativi che riducono il lordo."),
    ("GROSS", "Lordo imponibile", None, ""),
    ("IMP", "Imponibili e basi di calcolo", None, "Valori intermedi: non entrano nel netto."),
    ("DETR", "Detrazioni d'imposta", None, "Detrazioni mensili: riducono l'IRPEF lorda."),
    ("DED", "Trattenute", None, "Come in Odoo le trattenute sono importi NEGATIVI."),
    ("PREV", "Contributi previdenziali c/dipendente", "DED", ""),
    ("FISC", "Ritenute fiscali", "DED", ""),
    ("ALTRE", "Altre trattenute", "DED", ""),
    ("ESENTE", "Somme non imponibili", None, "Pagate in busta ma senza contributi né IRPEF."),
    ("CRED", "Somme anticipate per conto dello Stato", "ESENTE", "L'azienda le recupera in F24."),
    ("NET", "Netto", None, ""),
    ("COMP", "Contributi a carico azienda", None, "Come la categoria 'Company Contribution' di Odoo."),
    ("TOT", "Totali aziendali", None, ""),
]

# (nome, partner, sezione F24, codice, tipo)
REGISTRI = [
    ("Dipendenti - netti da pagare", "Dipendenti", "", "", "debito"),
    ("INPS - contributi", "INPS", "inps", "DM10", "debito"),
    ("INAIL - premio", "INAIL", "inail", "", "debito"),
    ("Erario - ritenute IRPEF (1001)", "Agenzia delle Entrate", "erario", "1001", "debito"),
    ("Erario - addizionale regionale (3802)", "Agenzia delle Entrate", "erario", "3802", "debito"),
    ("Erario - addizionale comunale saldo (3848)", "Agenzia delle Entrate", "erario", "3848", "debito"),
    ("Credito - trattamento integrativo (1655)", "Agenzia delle Entrate", "erario", "1655", "credito"),
    ("Credito - somma esente cuneo fiscale", "Agenzia delle Entrate", "erario", "CUNEO", "credito"),
    ("Fondo TFR", "Fondo TFR aziendale", "", "", "debito"),
]

PY = "python"
R = dict  # leggibilità

# Regole. Chiavi = campi di hr.salary.rule.  'struct' = strutture in cui inserirla.
REGOLE = [
    # --- struttura BASE (come 'Base for new structures' di Odoo)
    R(code="BASIC", name="Paga base (minimo tabellare)", sequence=1, category="BASIC", struct=["BASE"],
      amount_select="code", amount_python_compute="result = arrotonda(contract.wage * contract.part_time / 100)",
      note="Minimo del livello CCNL, riproporzionato se il contratto è part-time."),
    R(code="GROSS", name="Lordo imponibile", sequence=100, category="GROSS", struct=["BASE", "IT13"],
      appears_on_payslip=False, amount_select="code",
      amount_python_compute="result = categories.BASIC + categories.ALW"),
    R(code="NET", name="Netto in busta", sequence=500, category="NET", struct=["BASE", "IT13"],
      register="Dipendenti - netti da pagare", amount_select="code",
      amount_python_compute="result = categories.BASIC + categories.ALW + categories.ESENTE + categories.DED",
      note="Le trattenute (DED) sono negative: il netto è una semplice somma."),
    # --- struttura mensile CCNL metalmeccanico
    R(code="SUPERMIN", name="Superminimo individuale", sequence=2, category="BASIC", struct=["IT_ORD"],
      condition_select=PY, condition_python="result = contract.superminimo > 0",
      amount_select="code", amount_python_compute="result = arrotonda(contract.superminimo * contract.part_time / 100)"),
    R(code="SCATTI", name="Scatti di anzianità", sequence=3, category="BASIC", struct=["IT_ORD"],
      condition_select="range", condition_range="contract.scatti_n", condition_range_min=1, condition_range_max=99,
      amount_select="code",
      amount_python_compute="result_qty = contract.scatti_n\nresult = arrotonda(contract.scatto_importo * contract.part_time / 100)",
      note="Esempio di condizione a INTERVALLO e di result_qty: quantità × importo."),
    R(code="ORARIA", name="Paga oraria", sequence=10, category=None, struct=["IT_ORD"], appears_on_payslip=False,
      amount_select="code",
      amount_python_compute="result = arrotonda(categories.BASIC / contract.divisore_orario, 5)",
      note="Senza categoria: non si somma a nulla, ma le regole successive la usano come variabile ORARIA."),
    R(code="STR25", name="Straordinario feriale 25%", sequence=20, category="STR", struct=["IT_ORD"],
      condition_select=PY, condition_python="result = inputs.STR25 and inputs.STR25.amount > 0",
      amount_select="percentage", quantity="inputs.STR25.amount", amount_percentage=125.0,
      amount_percentage_base="ORARIA", inputs=[("STR25", "Ore di straordinario feriale (25%)")],
      note="Importo a PERCENTUALE: ore × 125% × paga oraria."),
    R(code="STR50", name="Straordinario festivo/notturno 50%", sequence=21, category="STR", struct=["IT_ORD"],
      condition_select=PY, condition_python="result = inputs.STR50 and inputs.STR50.amount > 0",
      amount_select="percentage", quantity="inputs.STR50.amount", amount_percentage=150.0,
      amount_percentage_base="ORARIA", inputs=[("STR50", "Ore di straordinario festivo/notturno (50%)")]),
    R(code="PREMIO", name="Premio una tantum", sequence=30, category="ALW", struct=["IT_ORD"],
      condition_select=PY, condition_python="result = inputs.PREMIO and inputs.PREMIO.amount",
      amount_select="code", amount_python_compute="result = inputs.PREMIO.amount",
      inputs=[("PREMIO", "Premio una tantum (lordo)")]),
    R(code="PNR", name="Permessi non retribuiti", sequence=40, category="ASS", struct=["IT_ORD"],
      condition_select=PY,
      condition_python="result = worked_days.PNR and worked_days.PNR.number_of_hours != 0",
      amount_select="percentage", quantity="abs(worked_days.PNR.number_of_hours)", amount_percentage=-100.0,
      amount_percentage_base="ORARIA",
      note="Usa i GIORNI LAVORATI: le ore di assenza di tipo PNR arrivano dal modulo Assenze."),
    R(code="IMP_PREV", name="Imponibile previdenziale", sequence=110, category="IMP", struct=["IT_ORD", "IT13"],
      appears_on_payslip=False, amount_select="code", amount_python_compute="result = arrotonda(GROSS, 0)",
      note="L'imponibile contributivo si arrotonda all'unità di euro."),
    R(code="INPS_DIP", name="Contributo IVS c/dipendente", sequence=120, category="PREV",
      struct=["IT_ORD", "IT13"], register="INPS - contributi", amount_select="percentage",
      amount_percentage=-9.19, amount_percentage_base="IMP_PREV",
      note="Percentuale NEGATIVA come la regola 'Provident Fund' della demo Odoo."),
    R(code="INPS_AGG", name="Contributo aggiuntivo 1% (oltre 1ª fascia)", sequence=121, category="PREV",
      parent="INPS_DIP", register="INPS - contributi", condition_select=PY,
      condition_python="result = IMP_PREV > payroll.MASSIMALE_1FASCIA_MESE",
      amount_select="percentage", amount_percentage=-1.0,
      amount_percentage_base="IMP_PREV - payroll.MASSIMALE_1FASCIA_MESE",
      note="Regola FIGLIA di INPS_DIP: viene valutata solo se la regola padre è applicabile. "
           "Semplificazione: nella realtà il superamento si verifica sul cumulo annuo."),
    R(code="IMP_FISC", name="Imponibile fiscale", sequence=200, category="IMP", struct=["IT_ORD", "IT13"],
      appears_on_payslip=False, amount_select="code", amount_python_compute="result = GROSS + categories.PREV",
      note="I contributi del dipendente sono deducibili (PREV è negativo)."),
    R(code="REDD_ANNUO", name="Reddito annuo presunto", sequence=210, category="IMP", struct=["IT_ORD"],
      appears_on_payslip=False, amount_select="code",
      amount_python_compute=("aliquota = abs(rules.INPS_DIP.amount_percentage)\n"
                             "result = arrotonda(contract.retribuzione_mensile * contract.mensilita"
                             " * (1 - aliquota / 100))"),
      note="Serve per detrazioni e cuneo. 'rules.INPS_DIP' è la regola già calcolata: se ne legge l'aliquota."),
    R(code="IRPEF_LORDA", name="IRPEF lorda", sequence=220, category="IMP", struct=["IT_ORD"],
      appears_on_payslip=False, amount_select="code",
      amount_python_compute="result = arrotonda(tools.irpef_annua(IMP_FISC * 12) / 12)",
      note="Scaglioni annui applicati all'imponibile del mese × 12, poi diviso 12."),
    R(code="DETR_LAV", name="Detrazioni lavoro dipendente", sequence=230, category="DETR", struct=["IT_ORD"],
      appears_on_payslip=False, amount_select="code",
      amount_python_compute="result = arrotonda(tools.detrazione_lavoro(REDD_ANNUO) / 12)"),
    R(code="DETR_FAM", name="Detrazioni familiari a carico", sequence=231, category="DETR", struct=["IT_ORD"],
      appears_on_payslip=False, condition_select=PY, condition_python="result = len(employee.familiari) > 0",
      amount_select="code",
      amount_python_compute="result = arrotonda(tools.detrazioni_familiari(REDD_ANNUO, employee.familiari) / 12)"),
    R(code="DETR_CUNEO", name="Ulteriore detrazione cuneo fiscale", sequence=232, category="DETR",
      struct=["IT_ORD"], appears_on_payslip=False, condition_select="range", condition_range="REDD_ANNUO",
      condition_range_min=20000.01, condition_range_max=40000, amount_select="code",
      amount_python_compute="result = arrotonda(tools.cuneo_detrazione(REDD_ANNUO) / 12)"),
    R(code="IRPEF", name="Ritenuta IRPEF", sequence=250, category="FISC", struct=["IT_ORD"],
      register="Erario - ritenute IRPEF (1001)", amount_select="code",
      amount_python_compute="result = -max(0, IRPEF_LORDA - categories.DETR)",
      note="IRPEF lorda meno tutte le detrazioni (categoria DETR), mai negativa."),
    R(code="ADD_REG", name="Addizionale regionale (rata)", sequence=260, category="FISC", struct=["IT_ORD"],
      register="Erario - addizionale regionale (3802)", condition_select=PY,
      condition_python="result = contract.add_reg_rata > 0",
      amount_select="code", amount_python_compute="result = -contract.add_reg_rata"),
    R(code="ADD_COM", name="Addizionale comunale (rata)", sequence=270, category="FISC", struct=["IT_ORD"],
      register="Erario - addizionale comunale saldo (3848)", condition_select=PY,
      condition_python="result = contract.add_com_rata > 0",
      amount_select="code", amount_python_compute="result = -contract.add_com_rata"),
    R(code="TRATT_INT", name="Trattamento integrativo", sequence=300, category="CRED", struct=["IT_ORD"],
      register="Credito - trattamento integrativo (1655)", condition_select=PY,
      condition_python="result = tools.trattamento_integrativo_spetta(REDD_ANNUO)",
      amount_select="fix", amount_fix=100.0, note="Ex bonus 100 €: 1.200 € l'anno, 100 € al mese."),
    R(code="IND_CUNEO", name="Somma esente cuneo fiscale", sequence=310, category="CRED", struct=["IT_ORD"],
      register="Credito - somma esente cuneo fiscale", condition_select="range", condition_range="REDD_ANNUO",
      condition_range_min=0.01, condition_range_max=20000, amount_select="code",
      amount_python_compute="result = arrotonda(tools.cuneo_indennita(REDD_ANNUO) / 12)"),
    R(code="TRASF", name="Indennità di trasferta Italia", sequence=320, category="ESENTE", struct=["IT_ORD"],
      condition_select=PY, condition_python="result = inputs.TRASF and inputs.TRASF.amount > 0",
      amount_select="fix", amount_fix=46.48, quantity="inputs.TRASF.amount",
      inputs=[("TRASF", "Giorni di trasferta in Italia")],
      note="Importo FISSO × quantità (giorni), come il 'Meal Voucher' della demo Odoo."),
    R(code="RIMBORSI", name="Rimborsi spese documentati", sequence=330, category="ESENTE", struct=["IT_ORD"],
      condition_select=PY, condition_python="result = inputs.RIMBORSI and inputs.RIMBORSI.amount",
      amount_select="code", amount_python_compute="result = inputs.RIMBORSI.amount",
      inputs=[("RIMBORSI", "Rimborsi spese documentati")]),
    R(code="ANTICIPO", name="Recupero anticipo", sequence=400, category="ALTRE", struct=["IT_ORD"],
      condition_select=PY, condition_python="result = inputs.ANTICIPO and inputs.ANTICIPO.amount",
      amount_select="code", amount_python_compute="result = -inputs.ANTICIPO.amount",
      inputs=[("ANTICIPO", "Anticipo già erogato da recuperare")]),
    R(code="INPS_DITTA", name="Contributi INPS c/azienda", sequence=600, category="COMP",
      struct=["IT_ORD", "IT13"], register="INPS - contributi", appears_on_payslip=False,
      amount_select="percentage", amount_percentage=29.58, amount_percentage_base="IMP_PREV"),
    R(code="INAIL", name="Premio INAIL (rateo)", sequence=610, category="COMP", struct=["IT_ORD", "IT13"],
      register="INAIL - premio", appears_on_payslip=False, amount_select="code",
      amount_python_compute="result = arrotonda(IMP_PREV * payroll.INAIL_TASSO / 1000)"),
    R(code="TFR", name="Quota TFR maturata", sequence=620, category="COMP", struct=["IT_ORD", "IT13"],
      register="Fondo TFR", appears_on_payslip=False, amount_select="code",
      amount_python_compute="result = arrotonda(GROSS / payroll.TFR_DIVISORE)"),
    R(code="COSTO", name="Costo aziendale", sequence=700, category="TOT", struct=["IT_ORD", "IT13"],
      appears_on_payslip=False, amount_select="code",
      amount_python_compute="result = GROSS + categories.ESENTE - categories.CRED + categories.COMP",
      note="Le somme della categoria CRED non sono un costo: si recuperano in F24."),
    # --- tredicesima
    R(code="TREDICESIMA", name="Tredicesima mensilità", sequence=1, category="BASIC", struct=["IT13"],
      amount_select="code",
      amount_python_compute=("result_qty = inputs.MESI_13 and inputs.MESI_13.amount or payroll.ratei_13\n"
                             "result = arrotonda(contract.retribuzione_mensile / 12)"),
      inputs=[("MESI_13", "Mesi maturati (vuoto = calcolo automatico)")],
      note="Ratei × retribuzione mensile / 12. I ratei si calcolano dal contratto (mese ≥ 15 giorni)."),
    R(code="IRPEF13", name="Ritenuta IRPEF (aliquota marginale)", sequence=250, category="FISC", struct=["IT13"],
      register="Erario - ritenute IRPEF (1001)", amount_select="code",
      amount_python_compute=("base = payroll.reddito_ordinario_annuo\n"
                             "result = -arrotonda(tools.irpef_annua(base + IMP_FISC) - tools.irpef_annua(base))"),
      note="Si tassa la tredicesima 'sopra' il reddito dei 12 mesi, senza detrazioni."),
]

STRUTTURE = [
    ("BASE", "Base per nuove strutture", None, "Come la struttura 'BASE' di Odoo: paga base, lordo e netto."),
    ("IT_ORD", "CCNL Metalmeccanico Industria - mensile", "BASE",
     "Eredita le regole della struttura BASE (padre) e aggiunge contributi, IRPEF, detrazioni, cuneo."),
    ("IT13", "CCNL Metalmeccanico Industria - tredicesima", None,
     "Struttura senza padre: riusa alcune regole della mensile (le regole sono condivise tra strutture)."),
]

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

TIPI_ASSENZA = [
    ("Ferie", "FERIE", 10, "#198754", False),
    ("Permessi retribuiti (ROL)", "ROL", 11, "#20c997", False),
    ("Malattia", "MAL", 12, "#dc3545", False),
    ("Infortunio", "INF", 13, "#fd7e14", False),
    ("Permesso non retribuito", "PNR", 14, "#6c757d", True),
    ("Congedo parentale", "CONG", 15, "#6f42c1", False),
]

# matr, cognome, nome, CF fittizio, nascita, luogo, comune, qualifica, mansione, reparto, email,
# contratto: (tipo, livello, superminimo, scatti, part-time, add reg, add com, data inizio, data fine)
DIPENDENTI = [
    ("0001", "Bianchi", "Marco", "BNCMRC85C12C745Q", date(1985, 3, 12), "Città di Castello", "Città di Castello",
     "operaio", "Addetto taglio laser", "Taglio", ("indeterminato", "C2", 0, 2, 100, 28.0, 12.0, date(2018, 4, 3), None)),
    ("0002", "Rossi", "Laura", "RSSLRA79H51G478K", date(1979, 6, 11), "Perugia", "Umbertide",
     "impiegato", "Contabilità e paghe", "Amministrazione",
     ("indeterminato", "B2", 150, 3, 100, 45.0, 18.0, date(2019, 1, 1), None)),
    ("0003", "Verdi", "Luca", "VRDLCU92T08C745M", date(1992, 12, 8), "Città di Castello", "Città di Castello",
     "operaio", "Piegatore pressa", "Piega", ("indeterminato", "C1", 0, 1, 100, 25.0, 10.0, date(2021, 2, 15), None)),
    ("0004", "Esposito", "Giuseppe", "SPSGPP76E20F839T", date(1976, 5, 20), "Napoli", "San Giustino",
     "operaio", "Saldatore MIG/TIG", "Saldatura", ("indeterminato", "C3", 80, 4, 100, 32.0, 14.0, date(2009, 1, 12), None)),
    ("0005", "Ferri", "Anna", "FRRNNA88P45D653W", date(1988, 9, 5), "Arezzo", "Citerna",
     "impiegato", "Ufficio commerciale (part-time)", "Commerciale",
     ("indeterminato", "C3", 0, 0, 50, 0.0, 0.0, date(2020, 10, 1), None)),
    ("0006", "Conti", "Davide", "CNTDVD04A17C745F", date(2004, 1, 17), "Città di Castello", "Città di Castello",
     "apprendista", "Apprendista saldatore", "Saldatura",
     ("apprendistato", "D2", 0, 0, 100, 0.0, 0.0, date(2025, 3, 3), date(2028, 3, 2))),
    ("0007", "Galli", "Sara", "GLLSRA80M60H501D", date(1980, 8, 20), "Roma", "Arezzo",
     "quadro", "Responsabile di produzione", "Direzione",
     ("indeterminato", "A1", 1900, 5, 100, 95.0, 40.0, date(2015, 5, 4), None)),
    ("0008", "Moretti", "Paolo", "MRTPLA97S03C745R", date(1997, 11, 3), "Città di Castello", "Città di Castello",
     "operaio", "Addetto imballaggio e pallet", "Packaging",
     ("determinato", "D2", 0, 0, 100, 0.0, 0.0, date(2026, 6, 1), date(2027, 5, 31))),
]

FAMILIARI = {
    "0001": [("coniuge", "Bianchi Giulia", date(1987, 4, 2), 100)],
    "0002": [("figlio", "Neri Tommaso", date(2003, 2, 10), 100)],
    "0004": [("coniuge", "Esposito Maria", date(1978, 1, 30), 100), ("figlio", "Esposito Ciro", date(2002, 7, 15), 50),
             ("figlio", "Esposito Anna", date(2011, 3, 3), 50)],
}

ASSENZE = [  # matr, tipo, dal, al, ore (dalle, alle) o None
    ("0003", "PNR", date(2026, 9, 14), date(2026, 9, 14), None),
    ("0003", "FERIE", date(2026, 9, 21), date(2026, 9, 22), None),
    ("0001", "ROL", date(2026, 9, 25), date(2026, 9, 25), (13.0, 17.0)),
    ("0002", "FERIE", date(2026, 10, 19), date(2026, 10, 23), None),
]

INPUT_SETTEMBRE = {"0001": {"STR25": 8}, "0004": {"STR50": 4, "TRASF": 2, "RIMBORSI": 45}, "0006": {"ANTICIPO": 200}}

ESERCITAZIONI = [
    ("Conosci Odoo Payroll",
     "Apri Configurazione → Strutture stipendio. La struttura IT_ORD ha come PADRE la struttura BASE: "
     "elenca le regole che eredita. Poi apri la regola SCATTI: che tipo di condizione usa? E INPS_DIP che tipo di importo?",
     "base"),
    ("La prima busta paga",
     "Libro paga → Buste paga dipendente → Nuova. Scegli Bianchi Marco, periodo 01/10/2026 - 31/10/2026. "
     "Guarda il tab 'Giorni lavorati e apporti': da dove arrivano i giorni e le festività? Inserisci 10 ore di STR25, "
     "premi 'Calcola scheda' e poi 'Conferma'. Annota il numero SLIP assegnato.", "base"),
    ("Gruppo buste paga di ottobre",
     "Libro paga → Gruppi buste paga → Nuovo: 'Ottobre 2026', dal 01/10 al 31/10. Premi 'Genera buste paga' "
     "selezionando tutti i dipendenti. Poi seleziona le buste e usa 'Cambia stato → Conferma'. Chiudi il gruppo.",
     "base"),
    ("Le assenze entrano in busta",
     "Assenze → Nuova: 1 giorno di Permesso non retribuito (PNR) per Moretti Paolo a ottobre, poi approvala. "
     "Nella sua busta di ottobre premi 'Riestrai dati busta paga' e ricalcola: quale regola usa i giorni lavorati?",
     "medio"),
    ("Leggi il calcolo riga per riga",
     "Apri la busta di settembre di Rossi Laura e il tab 'Calcolo stipendio'. Rifai a mano INPS (9,19% "
     "dell'imponibile arrotondato), IRPEF lorda, detrazioni (lavoro + figlio di 23 anni) e netto.", "medio"),
    ("Lo storno",
     "Sulla busta confermata di settembre di Conti Davide premi 'Storno'. Che cosa succede? Guarda la nota di credito "
     "creata, il registro dei messaggi in fondo alla pagina e il riepilogo F24 di settembre prima e dopo.", "medio"),
    ("Crea una regola con regola figlia",
     "Crea la regola IND_TURNO 'Indennità di turno' (categoria ALW, sequenza 25, condizione Python "
     "result = employee.department == 'Saldatura', importo fisso 50) e aggiungila alla struttura IT_ORD. Poi crea una "
     "regola FIGLIA 'Maggiorazione notturna' con importo fisso 20. Ricalcola Esposito e Conti.", "avanzato"),
    ("Tredicesima con struttura del gruppo",
     "Crea il gruppo 'Tredicesima 2026' (01/12 - 31/12) con Struttura = IT13. Genera le buste: perché Moretti ha "
     "meno ratei? Perché l'IRPEF è proporzionalmente più alta?", "avanzato"),
    ("Registri contributi e F24",
     "Configurazione → Registri contributi → Report: stampa le righe di settembre per INPS ed Erario 1001. "
     "Confronta con la pagina Versamenti F24 e prepara a mano il modello F24 con scadenza 16/10/2026.", "avanzato"),
    ("Verifica critica",
     "Le aliquote e i parametri sono didattici. Scegli 3 valori (aliquota INPS, scaglioni IRPEF, massimale 1ª fascia), "
     "cercali su fonti ufficiali (INPS, Agenzia delle Entrate, Gazzetta Ufficiale), correggili e misura l'effetto.",
     "avanzato"),
]


def _cal(ws_id, name, days, morning, afternoon=None):
    cal = ResourceCalendar(workspace_id=ws_id, name=name,
                           hours_per_day=(morning[1] - morning[0]) + ((afternoon[1] - afternoon[0]) if afternoon else 0))
    nomi = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
    for d in days:
        cal.attendance_ids.append(ResourceCalendarAttendance(name=f"{nomi[d]} mattina", dayofweek=d,
                                                             hour_from=morning[0], hour_to=morning[1]))
        if afternoon:
            cal.attendance_ids.append(ResourceCalendarAttendance(name=f"{nomi[d]} pomeriggio", dayofweek=d,
                                                                 hour_from=afternoon[0], hour_to=afternoon[1]))
    db.session.add(cal)
    return cal


def seed_workspace(ws: Workspace, with_example=True):
    from . import payroll
    ws.name = "Ferro & Transenne Srl"
    ws.vat = "IT00000000000 (fittizia)"
    ws.street = "Via dell'Industria 12"
    ws.city = "06012 Città di Castello (PG)"
    ws.email = "paghe@ferroetransenne.example"
    ws.ccnl = "CCNL Metalmeccanica Industria"
    ws.matricola_inps = "0000000000"
    ws.pat_inail = "00000000/00"
    ws.slip_sequence_next = 1
    ws_id = ws.id

    for cod, descr, val, unita in PARAMETRI:
        db.session.add(Parametro(workspace_id=ws_id, codice=cod, descrizione=descr, valore=val, unita=unita))
    for da, a, aliq in SCAGLIONI_IRPEF_DEFAULT:
        db.session.add(ScaglioneIrpef(workspace_id=ws_id, da=da, a=a, aliquota=aliq))
    livelli = {}
    for cod, descr, minimo, scatto in LIVELLI:
        livelli[cod] = Livello(workspace_id=ws_id, codice=cod, descrizione=descr, minimo=minimo, scatto_importo=scatto)
        db.session.add(livelli[cod])

    full = _cal(ws_id, "Tempo pieno 40 ore (lun-ven 8-12 / 13-17)", range(5), (8.0, 12.0), (13.0, 17.0))
    part = _cal(ws_id, "Part-time 20 ore (lun-ven 8-12)", range(5), (8.0, 12.0))
    for y in (2026, 2027):
        for d, n in italian_holidays(y):
            db.session.add(ResourceCalendarLeave(workspace_id=ws_id, name=n, date=d))
        db.session.add(ResourceCalendarLeave(workspace_id=ws_id, name="San Florido (patrono)", date=date(y, 11, 13)))
    tipi = {}
    for name, code, seq, color, unpaid in TIPI_ASSENZA:
        tipi[code] = LeaveType(workspace_id=ws_id, name=name, code=code, sequence=seq, color=color, unpaid=unpaid)
        db.session.add(tipi[code])

    cats = {}
    for code, name, parent, note in CATEGORIE:
        cats[code] = SalaryRuleCategory(workspace_id=ws_id, code=code, name=name, note=note,
                                        parent=cats.get(parent) if parent else None)
        db.session.add(cats[code])
    partners, regs = {}, {}
    for name, pname, sez, cod, tipo in REGISTRI:
        if pname not in partners:
            partners[pname] = Partner(workspace_id=ws_id, name=pname)
            db.session.add(partners[pname])
        regs[name] = ContributionRegister(workspace_id=ws_id, name=name, partner=partners[pname],
                                          f24_sezione=sez, f24_codice=cod, f24_tipo=tipo)
        db.session.add(regs[name])
    structs = {}
    for code, name, parent, note in STRUTTURE:
        structs[code] = PayrollStructure(workspace_id=ws_id, code=code, name=name, note=note,
                                         parent=structs.get(parent) if parent else None)
        db.session.add(structs[code])
    rules = {}
    for spec in REGOLE:
        spec = dict(spec)
        struct_codes = spec.pop("struct", [])
        cat = spec.pop("category", None)
        reg = spec.pop("register", None)
        parent = spec.pop("parent", None)
        inputs = spec.pop("inputs", [])
        rule = SalaryRule(workspace_id=ws_id, category=cats.get(cat) if cat else None,
                          register=regs.get(reg) if reg else None,
                          parent_rule=rules.get(parent) if parent else None, **spec)
        for icode, iname in inputs:
            rule.input_ids.append(RuleInput(code=icode, name=iname))
        for sc in struct_codes:
            structs[sc].rule_ids.append(rule)
        db.session.add(rule)
        rules[rule.code] = rule
    db.session.flush()

    emps = {}
    for (matr, cogn, nome, cf, nascita, luogo, comune, qual, mans, rep, (tipo, liv, supermin, scatti, pt, areg, acom,
                                                                         dstart, dend)) in DIPENDENTI:
        cal = part if pt < 100 else full
        e = Employee(workspace_id=ws_id, registration_number=matr, last_name=cogn, first_name=nome,
                     identification_id=cf, birthday=nascita, place_of_birth=luogo, private_city=comune,
                     qualifica=qual, job_title=mans, department=rep, resource_calendar=cal,
                     work_email=f"{nome.lower()}.{cogn.lower()}@ferroetransenne.example",
                     bank_account=f"IT00X0000000000000000{matr}")
        lv = livelli[liv]
        e.contract_ids.append(Contract(
            workspace_id=ws_id, name=f"{cogn} {nome} - {tipo} {liv}", state="open", contract_type=tipo,
            job_title=mans, department=rep, date_start=dstart, date_end=dend, resource_calendar=cal,
            wage=lv.minimo, struct=structs["IT_ORD"], schedule_pay="monthly", ccnl=ws.ccnl, livello=lv,
            superminimo=supermin, scatti_n=scatti, scatto_importo=lv.scatto_importo, part_time=pt,
            mensilita=13, divisore_orario=173, add_reg_rata=areg, add_com_rata=acom,
            trial_date_end=None))
        for rel, nome_f, nascita_f, perc in FAMILIARI.get(matr, []):
            e.familiari.append(Familiare(relazione=rel, nome=nome_f, data_nascita=nascita_f, percentuale=perc))
        db.session.add(e)
        emps[matr] = e
    # contratto precedente (scaduto) di Rossi: storico delle versioni contrattuali
    rossi = emps["0002"]
    rossi.contract_ids.insert(0, Contract(
        workspace_id=ws_id, name="Rossi Laura - indeterminato B1", state="close", contract_type="indeterminato",
        job_title="Impiegata amministrativa", department="Amministrazione", date_start=date(2012, 9, 1),
        date_end=date(2018, 12, 31), resource_calendar=full, wage=livelli["B1"].minimo, struct=structs["IT_ORD"],
        ccnl=ws.ccnl, livello=livelli["B1"], scatti_n=2, scatto_importo=livelli["B1"].scatto_importo, mensilita=13))
    for matr, code, d1, d2, ore in ASSENZE:
        db.session.add(Leave(workspace_id=ws_id, employee=emps[matr], holiday_status=tipi[code], date_from=d1,
                             date_to=d2, request_unit_hours=bool(ore), hour_from=ore[0] if ore else None,
                             hour_to=ore[1] if ore else None, state="validate", name=tipi[code].name))
    db.session.flush()

    if with_example:
        run = PayslipRun(workspace_id=ws_id, name="Settembre 2026", date_start=date(2026, 9, 1),
                         date_end=date(2026, 9, 30))
        db.session.add(run)
        db.session.flush()
        slips, errors = payroll.generate_payslips(run, sorted(emps.values(), key=lambda e: e.registration_number),
                                                  author="Dati iniziali")
        for slip in slips:
            vals = INPUT_SETTEMBRE.get(slip.employee.registration_number, {})
            if vals:
                for i in slip.input_line_ids:
                    if i.code in vals:
                        i.amount = vals[i.code]
                db.session.flush()
                payroll.compute_sheet(slip, author="Dati iniziali")
            payroll.action_payslip_done(slip, author="Dati iniziali")
        run.state = "close"
        if errors:
            raise RuntimeError("Errore nei dati demo: " + "; ".join(errors))
    db.session.commit()


def clear_workspace(ws: Workspace):
    ws_id = ws.id
    from .models import Payslip
    for slip in Payslip.query.filter_by(workspace_id=ws_id).all():
        slip.refunded_id = None
    db.session.flush()
    for rule in SalaryRule.query.filter_by(workspace_id=ws_id).all():
        rule.parent_rule_id = None
        rule.struct_ids = []
    for cat in SalaryRuleCategory.query.filter_by(workspace_id=ws_id).all():
        cat.parent_id = None
    for st in PayrollStructure.query.filter_by(workspace_id=ws_id).all():
        st.parent_id = None
    db.session.flush()
    for model in WORKSPACE_MODELS:
        if hasattr(model, "workspace_id"):
            model.query.filter_by(workspace_id=ws_id).delete(synchronize_session=False)
    db.session.commit()


def reset_workspace(ws: Workspace):
    clear_workspace(ws)
    ws.reset_at = now()
    for f in ("leaves_positive", "allow_cancel_payslips", "allow_edit_payslip_lines", "require_code_and_category"):
        setattr(ws, f, False)
    ws.prevent_compute_on_confirm = True
    seed_workspace(ws)


def seed_esercitazioni():
    if Esercitazione.query.count():
        return
    for i, (titolo, testo, livello) in enumerate(ESERCITAZIONI, start=1):
        db.session.add(Esercitazione(ordine=i, titolo=titolo, testo=testo, livello=livello))
    db.session.commit()


__all__ = ["seed_workspace", "reset_workspace", "clear_workspace", "seed_esercitazioni", "PayslipInput"]
