"""Lezioni brevi dei sei laboratori dell'AI Lab e quiz del laboratorio «Regole e rischi».

Riferimenti normativi da ricontrollare a ogni edizione (cambiano spesso): AI Act (Reg. UE 2024/1689) e date di applicazione
degli obblighi per i sistemi ad alto rischio, rinviate dal pacchetto Omnibus digitale; GDPR (Reg. UE 2016/679); art. 4
della L. 300/1970 (Statuto dei lavoratori); L. 132/2025 sull'intelligenza artificiale.
"""

LABORATORI = [
    {"id": "anomalie", "n": 3, "titolo": "Anomalie prima della chiusura", "icona": "bi-activity",
     "sintesi": "24 mesi di storico con anomalie nascoste: regole, statistica e Isolation Forest, poi le cause dell'aumento di costo di un reparto."},
    {"id": "presenze", "n": 2, "titolo": "Presenze e note spese", "icona": "bi-file-earmark-spreadsheet",
     "sintesi": "Excel disordinato, badge, PDF e foto di uno scontrino diventano gli apporti delle buste di novembre."},
    {"id": "ccnl", "n": 1, "titolo": "Assistente CCNL", "icona": "bi-journal-text",
     "sintesi": "Domande in italiano su metalmeccanico, commercio e logistica: risposta con articolo, pagina e citazione."},
    {"id": "confronto", "n": 5, "titolo": "Seconda opinione", "icona": "bi-intersect",
     "sintesi": "Le buste di novembre ricalcolate con ccnl-engine e confrontate con MasterPayroll: spiegare le differenze."},
    {"id": "sportello", "n": 4, "titolo": "Sportello HR", "icona": "bi-chat-dots",
     "sintesi": "L'assistente che risponde ai dipendenti su ferie, permessi, buste e regole aziendali, e sa quando fermarsi."},
    {"id": "regole", "n": 6, "titolo": "Regole e rischi", "icona": "bi-shield-check",
     "sintesi": "AI Act, GDPR e controlli a distanza: che cosa si può fare con l'AI sui dati dei lavoratori."},
]

LEZIONI = {
"anomalie": """
<p>Prima di chiudere le paghe del mese il controllo si fa spesso a campione: qualche busta, i totali, il confronto con il
mese prima. Gli errori che sfuggono sono quelli piccoli e ripetuti o quelli «plausibili». Qui li cerchiamo con tre metodi che
si completano:</p>
<ul>
<li><b>Regole</b>: controlli certi che l'ufficio paghe sa scrivere (un dipendente, un mese, una busta; niente busta fuori dal
contratto; il part-time non si paga pieno; gli scatti non diminuiscono; i rimborsi oltre soglia si giustificano; l'aliquota
contributiva deve essere quella della qualifica). Trovano sempre quello per cui sono scritte, e solo quello.</li>
<li><b>Statistica</b>: ogni dipendente contro la sua storia. Lo <b>z-score robusto</b> usa mediana e MAD (deviazione assoluta
mediana) invece di media e deviazione standard, così un mese strano non sposta il riferimento:
<code>z = 0,6745 × (valore − mediana) ÷ MAD</code>; oltre 3,5 la riga si segnala.</li>
<li><b>Machine learning</b>: l'<b>Isolation Forest</b> costruisce centinaia di alberi che dividono a caso i dati; le righe
che si isolano con pochi tagli sono quelle diverse da tutte le altre. Non serve sapere in anticipo che cosa cercare, ma va
interpretato: segnala anche righe legittime.</li>
</ul>
<p>Nessun metodo basta da solo: le regole non vedono gli straordinari «gonfiati», la statistica non vede una busta doppia, il
machine learning non spiega il perché. E una segnalazione non è un errore finché una persona non l'ha verificata: una
trasferta di sei giorni può essere vera.</p>
<p><b>Dal numero alle cause.</b> Quando il costo di un reparto sale, il controller lo divide in <b>effetto ore</b> (si è
lavorato di più) ed <b>effetto costo orario</b> (ogni ora è costata di più), poi cerca le voci che spiegano la differenza,
dipendente per dipendente: retribuzione, straordinari, trasferte, rimborsi, contributi.</p>
<p class="mb-0"><b>Da provare in Python</b> (anche su Google Colab) con il CSV dello storico:
<code>from sklearn.ensemble import IsolationForest; m = IsolationForest(contamination=0.05, random_state=42).fit(X);
punteggi = -m.score_samples(X)</code>.</p>
""",
"presenze": """
<p>Le presenze arrivano in tutti i formati: il foglio Excel dei capi reparto con nomi scritti a mano e sigle, il file delle
timbrature del badge, le note spese in PDF, la foto di uno scontrino. Trasferirle a mano nel gestionale è lento e pieno di
errori. Una procedura automatica fa quattro cose:</p>
<ol>
<li><b>Legge</b> ogni formato con il lettore adatto (Excel, CSV, PDF con testo; per le foto serve un modello che «vede»,
cioè un modello linguistico con visione, oppure l'inserimento a mano);</li>
<li><b>normalizza</b> nomi e valori: «ESPOSITO PINO» è Esposito Giuseppe? «8h», «8,5» e «otto» sono ore? Un'uscita mancante
dal badge che orario prende?</li>
<li><b>applica le regole</b> del contratto e dell'azienda: ore oltre l'orario = straordinario 25%, festivi 50%, trasferta =
indennità forfettaria, niente rimborso dei pasti a chi ha già la trasferta, chilometri × 0,40 €;</li>
<li><b>si ferma</b> sui casi dubbi e chiede a una persona: è il punto più importante. Una procedura che «indovina» un nome o
un orario sbaglia in silenzio.</li>
</ol>
<p class="mb-0">Il risultato sono gli <b>apporti</b> delle buste (STR25, STR50, TRASF, RIMBORSI) e le <b>assenze</b> da
registrare (ferie, permessi, malattia). Un modello linguistico può leggere le foto e i testi liberi, ma il suo risultato va
sempre confermato prima di finire in busta.</p>
""",
"ccnl": """
<p>Un dubbio sul contratto («quanto si paga lo straordinario?», «quanto dura il comporto?») costa tempo: il testo è lungo,
gli accordi di rinnovo cambiano i numeri. Un assistente utile non «inventa» la risposta: la <b>trova</b> in una banca dati e
dice <b>da dove viene</b>. È lo schema RAG (Retrieval-Augmented Generation): prima si cerca il pezzo giusto, poi lo si
presenta (e, se c'è un modello linguistico, lo si riformula senza aggiungere nulla).</p>
<p>Qui la banca dati sono le regole strutturate di <b>ccnl-engine</b> (progetto open source, licenza MIT) per tre contratti:
metalmeccanico Federmeccanica, commercio Confcommercio, logistica Confetra. Ogni scheda ha il valore, l'articolo, la pagina,
la citazione del testo e lo <b>stato di verifica</b>. La ricerca usa il punteggio <b>BM25</b>, lo stesso dei motori di ricerca:
contano le parole della domanda che compaiono nella scheda, pesate per quanto sono rare.</p>
<p class="mb-0"><b>Attenzione</b>: molti valori di ccnl-engine sono estratti con l'AI e revisionati solo da un'AI. Prima di
usarli in busta si controlla sempre la citazione sul testo firmato. E se la banca dati non contiene una regola (per esempio
la trasferta nel metalmeccanico), l'assistente deve dirlo, non improvvisare.</p>
""",
"confronto": """
<p>Un secondo calcolo indipendente è il modo più semplice per scoprire un errore di impostazione: tabelle vecchie, scatti non
aggiornati, aliquote sbagliate. Qui le buste di novembre 2026 dei dipendenti di Ferro & Transenne sono ricalcolate con
<b>ccnl-engine</b> sul CCNL metalmeccanico Federmeccanica e confrontate con MasterPayroll.</p>
<p>Le differenze non sono tutte errori. I minimi del gestionale del corso sono <b>indicativi</b>; il motore conta gli scatti
dall'anzianità, il gestionale li legge dal contratto; l'aliquota contributiva dipende da dimensione e settore dell'azienda;
l'apprendista ha percentuali proprie. Il lavoro è <b>spiegare</b> ogni differenza e decidere chi ha ragione, citando la fonte.</p>
<p class="mb-0">ccnl-engine dice sempre se un risultato è «pagabile»: qui non lo è mai, perché mancano dati che il motore
chiede esplicitamente (addizionali, familiari, fondo pensione…). È un comportamento corretto: meglio un calcolo che dichiara
quello che non sa di uno che lo nasconde.</p>
""",
"sportello": """
<p>Una parte grande del lavoro dell'ufficio paghe sono domande ripetute: ferie residue, netto del mese, CU, rimborsi. Uno
sportello automatico risponde subito a quelle sicure e passa le altre a una persona. Per farlo bene servono tre cose:</p>
<ul>
<li><b>dati del dipendente che chiede, e solo quelli</b>: ferie e permessi maturati e goduti, buste completate. Le domande sui
colleghi si rifiutano;</li>
<li><b>regole aziendali scritte</b> (rimborsi, trasferte, malattia, ferie): l'assistente le cita, non le inventa;</li>
<li><b>un limite chiaro</b>: niente promesse su importi, niente decisioni sul rapporto di lavoro; quello che non sa si inoltra.</li>
</ul>
<p class="mb-0">Per l'AI Act chi parla con un sistema di AI deve saperlo (obbligo di trasparenza); per il GDPR ogni domanda
contiene dati personali, quindi si registra con criterio e si conserva il minimo necessario.</p>
""",
"regole": """
<p>Usare l'AI sui dati dei lavoratori è possibile, ma dentro regole precise.</p>
<ul>
<li><b>AI Act (Reg. UE 2024/1689)</b>. Sono <b>ad alto rischio</b> (allegato III, punto 4) i sistemi usati per selezionare e
assumere, per prendere decisioni che incidono sul rapporto di lavoro (promozioni, licenziamenti), per assegnare compiti in
base al comportamento o per <b>monitorare e valutare</b> prestazioni e comportamento dei lavoratori. Richiedono gestione dei
rischi, dati di qualità, documentazione, sorveglianza umana e informazione ai lavoratori e ai loro rappresentanti. Le date
di applicazione di questi obblighi sono state rinviate dal pacchetto Omnibus digitale: vanno verificate. Chi usa un
chatbot deve far sapere alle persone che parlano con un'AI (art. 50). Sono vietati, tra l'altro, i sistemi che riconoscono
le emozioni sul luogo di lavoro (art. 5).</li>
<li><b>GDPR</b>. Serve una base giuridica, si usano solo i dati necessari (minimizzazione), si informano i dipendenti. Le
decisioni basate <b>unicamente</b> su un trattamento automatizzato con effetti significativi sulla persona sono limitate
(art. 22): l'AI propone, una persona decide. Per trattamenti sistematici sui lavoratori serve di norma la valutazione
d'impatto (DPIA). Malattia e salute sono categorie particolari di dati.</li>
<li><b>Statuto dei lavoratori, art. 4</b>. Gli strumenti da cui può derivare un controllo a distanza dei lavoratori si
installano solo per esigenze organizzative, produttive, di sicurezza o di tutela del patrimonio, previo accordo sindacale o
autorizzazione dell'Ispettorato; i dati raccolti si usano solo con adeguata informazione ai lavoratori.</li>
<li><b>Legge italiana sull'AI (L. 132/2025)</b>: nel lavoro l'AI deve migliorare le condizioni e la produttività senza
ledere dignità e riservatezza; il datore informa il lavoratore dell'uso dei sistemi di AI.</li>
</ul>
<p class="mb-0"><b>In pratica, per i laboratori di questo corso</b>: il controllo delle anomalie sulle buste è un controllo
amministrativo su errori di calcolo, non una valutazione delle persone; lo diventa se si usano i dati per giudicare chi
lavora di più o di meno. Lo sportello dichiara di essere automatico e non decide nulla. I dati restano nel gestionale; al
modello linguistico esterno, se attivo, vanno solo testi dei contratti e domande generali.</p>
""",
}

QUIZ_REGOLE = [
    ("Un sistema di AI che valuta le prestazioni dei lavoratori per decidere i premi, per l'AI Act è…",
     ["vietato sempre", "ad alto rischio", "a rischio minimo, senza obblighi"], 1),
    ("Un chatbot HR per i dipendenti deve…",
     ["dichiarare di essere un sistema di AI", "fingersi una persona per sembrare più cortese", "essere approvato dall'INPS"], 0),
    ("Il riconoscimento delle emozioni dei lavoratori con l'AI sul luogo di lavoro è…",
     ["consentito con il consenso", "vietato dall'AI Act, salvo motivi medici o di sicurezza", "obbligatorio per la sicurezza"], 1),
    ("Per il GDPR, una decisione sul lavoratore presa solo dall'algoritmo, con effetti significativi…",
     ["è sempre libera", "è limitata: serve l'intervento umano e il diritto di contestarla", "è permessa se il software è certificato"], 1),
    ("Un'anomalia trovata dall'Isolation Forest su una busta paga è…",
     ["un errore certo da correggere subito", "una segnalazione da verificare da una persona", "una prova di comportamento scorretto"], 1),
    ("Uno strumento che permette di controllare a distanza l'attività dei lavoratori richiede (art. 4 Statuto)…",
     ["solo una mail ai dipendenti", "accordo sindacale o autorizzazione dell'Ispettorato e informativa", "nulla, se l'azienda ha meno di 15 dipendenti"], 1),
    ("Al modello linguistico esterno dell'AI Lab si possono mandare…",
     ["i cedolini completi dei dipendenti", "testi dei contratti e domande generali", "i certificati di malattia"], 1),
    ("I dati sulla malattia dei dipendenti, per il GDPR, sono…",
     ["dati comuni", "categorie particolari di dati (salute)", "dati pubblici"], 1),
    ("La valutazione d'impatto (DPIA) serve…",
     ["per i trattamenti che presentano rischi elevati, come quelli sistematici sui lavoratori", "solo per le banche", "solo dopo una violazione dei dati"], 0),
    ("Se l'assistente CCNL non trova la regola nella sua banca dati deve…",
     ["dare comunque una risposta plausibile", "dire che non la trova e indicare di consultare il testo", "usare il valore di un altro contratto"], 1),
]
