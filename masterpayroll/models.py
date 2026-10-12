from datetime import date, datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def now():
    """Ora UTC senza fuso (colonne DateTime semplici)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Utenti, ambienti formativi, tracciamento attività
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="allievo")  # docente | allievo
    classe = db.Column(db.String(80), default="")
    active_flag = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=now)
    last_seen = db.Column(db.DateTime)

    workspace = db.relationship("Workspace", back_populates="owner", uselist=False,
                                cascade="all, delete-orphan")

    def set_password(self, pwd):
        self.password_hash = generate_password_hash(pwd)

    def check_password(self, pwd):
        return check_password_hash(self.password_hash, pwd)

    @property
    def is_docente(self):
        return self.role == "docente"

    @property
    def is_active(self):
        return bool(self.active_flag)


class Workspace(db.Model):
    """Ambiente isolato: ogni allievo (e il docente) ha la sua azienda simulata."""
    __tablename__ = "workspaces"
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now)
    reset_at = db.Column(db.DateTime)

    ragione_sociale = db.Column(db.String(160), default="")
    partita_iva = db.Column(db.String(20), default="")
    indirizzo = db.Column(db.String(200), default="")
    ccnl = db.Column(db.String(160), default="")
    pat_inail = db.Column(db.String(40), default="")
    matricola_inps = db.Column(db.String(40), default="")

    owner = db.relationship("User", back_populates="workspace")


class Attivita(db.Model):
    """Log delle azioni dell'allievo: base per il calcolo delle ore reali."""
    __tablename__ = "attivita"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ts = db.Column(db.DateTime, default=now, index=True)
    metodo = db.Column(db.String(10))
    path = db.Column(db.String(255))


class Esercitazione(db.Model):
    """Esercizi proposti dal docente (comuni a tutta la classe)."""
    __tablename__ = "esercitazioni"
    id = db.Column(db.Integer, primary_key=True)
    ordine = db.Column(db.Integer, default=0)
    titolo = db.Column(db.String(200), nullable=False)
    testo = db.Column(db.Text, default="")
    livello = db.Column(db.String(20), default="base")
    attiva = db.Column(db.Boolean, default=True)


class EsercitazioneSvolta(db.Model):
    __tablename__ = "esercitazioni_svolte"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    esercitazione_id = db.Column(db.Integer, db.ForeignKey("esercitazioni.id", ondelete="CASCADE"))
    consegnata_at = db.Column(db.DateTime, default=now)
    nota = db.Column(db.Text, default="")
    __table_args__ = (db.UniqueConstraint("user_id", "esercitazione_id"),)


# ---------------------------------------------------------------------------
# Tabelle di configurazione (per ambiente)
# ---------------------------------------------------------------------------
class WsMixin:
    @classmethod
    def ws_col(cls):
        return db.Column(db.Integer, db.ForeignKey("workspaces.id", ondelete="CASCADE"),
                         index=True, nullable=False)


class Parametro(db.Model):
    __tablename__ = "parametri"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    codice = db.Column(db.String(40), nullable=False)
    descrizione = db.Column(db.String(200), default="")
    valore = db.Column(db.Float, default=0.0)
    unita = db.Column(db.String(20), default="")


class ScaglioneIrpef(db.Model):
    __tablename__ = "scaglioni_irpef"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    da = db.Column(db.Float, nullable=False)
    a = db.Column(db.Float)  # None = oltre
    aliquota = db.Column(db.Float, nullable=False)


class Livello(db.Model):
    __tablename__ = "livelli"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    codice = db.Column(db.String(10), nullable=False)
    descrizione = db.Column(db.String(200), default="")
    minimo = db.Column(db.Float, default=0.0)
    scatto_importo = db.Column(db.Float, default=0.0)


class Categoria(db.Model):
    """Categoria di regola (come hr.salary.rule.category di Odoo)."""
    __tablename__ = "categorie"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    codice = db.Column(db.String(20), nullable=False)
    nome = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(20), default="info")  # competenza | trattenuta | info
    sequenza = db.Column(db.Integer, default=10)


class Struttura(db.Model):
    """Struttura retributiva: insieme ordinato di regole (hr.payroll.structure)."""
    __tablename__ = "strutture"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    codice = db.Column(db.String(30), nullable=False)
    nome = db.Column(db.String(160), nullable=False)
    tipo_cedolino = db.Column(db.String(20), default="ordinaria")  # ordinaria | tredicesima
    descrizione = db.Column(db.Text, default="")

    regole = db.relationship("Regola", back_populates="struttura",
                             order_by="Regola.sequenza", cascade="all, delete-orphan")


class Regola(db.Model):
    """Regola salariale (hr.salary.rule): condizione + formula."""
    __tablename__ = "regole"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    struttura_id = db.Column(db.Integer, db.ForeignKey("strutture.id", ondelete="CASCADE"))
    sequenza = db.Column(db.Integer, default=100)
    codice = db.Column(db.String(30), nullable=False)
    nome = db.Column(db.String(160), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorie.id"))
    condizione = db.Column(db.Text, default="")
    formula = db.Column(db.Text, default="0")
    quantita_formula = db.Column(db.Text, default="")
    base_formula = db.Column(db.Text, default="")
    stampa = db.Column(db.Boolean, default=True)
    registro = db.Column(db.String(40), default="")
    note = db.Column(db.Text, default="")
    attiva = db.Column(db.Boolean, default=True)

    struttura = db.relationship("Struttura", back_populates="regole")
    categoria = db.relationship("Categoria")


# ---------------------------------------------------------------------------
# Anagrafiche
# ---------------------------------------------------------------------------
class Dipendente(db.Model):
    __tablename__ = "dipendenti"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    matricola = db.Column(db.String(20), nullable=False)
    cognome = db.Column(db.String(80), nullable=False)
    nome = db.Column(db.String(80), nullable=False)
    codice_fiscale = db.Column(db.String(16), default="")
    data_nascita = db.Column(db.Date)
    comune_residenza = db.Column(db.String(80), default="")
    data_assunzione = db.Column(db.Date)
    data_cessazione = db.Column(db.Date)
    qualifica = db.Column(db.String(20), default="operaio")  # operaio | impiegato | apprendista
    mansione = db.Column(db.String(120), default="")
    reparto = db.Column(db.String(60), default="")
    attivo = db.Column(db.Boolean, default=True)

    contratti = db.relationship("Contratto", back_populates="dipendente",
                                cascade="all, delete-orphan", order_by="Contratto.data_inizio")

    @property
    def nominativo(self):
        return f"{self.cognome} {self.nome}"

    @property
    def contratto_attivo(self):
        for c in reversed(self.contratti):
            if c.attivo:
                return c
        return None


class Contratto(db.Model):
    __tablename__ = "contratti"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    dipendente_id = db.Column(db.Integer, db.ForeignKey("dipendenti.id", ondelete="CASCADE"))
    tipo = db.Column(db.String(30), default="indeterminato")  # indeterminato | determinato | apprendistato
    livello_id = db.Column(db.Integer, db.ForeignKey("livelli.id"))
    struttura_id = db.Column(db.Integer, db.ForeignKey("strutture.id"))
    minimo = db.Column(db.Float, default=0.0)
    superminimo = db.Column(db.Float, default=0.0)
    scatti_n = db.Column(db.Integer, default=0)
    scatto_importo = db.Column(db.Float, default=0.0)
    part_time = db.Column(db.Float, default=100.0)  # percentuale
    ore_settimanali = db.Column(db.Float, default=40.0)
    divisore_orario = db.Column(db.Float, default=173.0)
    add_reg_rata = db.Column(db.Float, default=0.0)
    add_com_rata = db.Column(db.Float, default=0.0)
    data_inizio = db.Column(db.Date, default=date.today)
    data_fine = db.Column(db.Date)
    attivo = db.Column(db.Boolean, default=True)

    dipendente = db.relationship("Dipendente", back_populates="contratti")
    livello = db.relationship("Livello")
    struttura = db.relationship("Struttura")

    @property
    def retribuzione_mensile(self):
        pt = (self.part_time or 0) / 100
        return round(((self.minimo or 0) + (self.superminimo or 0)) * pt
                     + (self.scatti_n or 0) * (self.scatto_importo or 0) * pt, 2)


# ---------------------------------------------------------------------------
# Elaborazioni e cedolini
# ---------------------------------------------------------------------------
class Elaborazione(db.Model):
    """Elaborazione mensile (hr.payslip.run): un lotto di cedolini."""
    __tablename__ = "elaborazioni"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    anno = db.Column(db.Integer, nullable=False)
    mese = db.Column(db.Integer, nullable=False)
    tipo = db.Column(db.String(20), default="ordinaria")
    descrizione = db.Column(db.String(200), default="")
    created_at = db.Column(db.DateTime, default=now)

    cedolini = db.relationship("Cedolino", back_populates="elaborazione")


class Cedolino(db.Model):
    __tablename__ = "cedolini"
    id = db.Column(db.Integer, primary_key=True)
    workspace_id = WsMixin.ws_col()
    elaborazione_id = db.Column(db.Integer, db.ForeignKey("elaborazioni.id", ondelete="SET NULL"))
    dipendente_id = db.Column(db.Integer, db.ForeignKey("dipendenti.id", ondelete="CASCADE"))
    contratto_id = db.Column(db.Integer, db.ForeignKey("contratti.id", ondelete="SET NULL"))
    struttura_id = db.Column(db.Integer, db.ForeignKey("strutture.id", ondelete="SET NULL"))
    anno = db.Column(db.Integer, nullable=False)
    mese = db.Column(db.Integer, nullable=False)
    tipo = db.Column(db.String(20), default="ordinaria")
    giorni_lavorati = db.Column(db.Float, default=26)
    ore_lavorate = db.Column(db.Float, default=0)
    stato = db.Column(db.String(20), default="bozza")  # bozza | calcolato | confermato
    lordo = db.Column(db.Float, default=0.0)
    netto = db.Column(db.Float, default=0.0)
    costo = db.Column(db.Float, default=0.0)
    errore = db.Column(db.Text, default="")
    calcolato_at = db.Column(db.DateTime)
    confermato_at = db.Column(db.DateTime)

    elaborazione = db.relationship("Elaborazione", back_populates="cedolini")
    dipendente = db.relationship("Dipendente")
    contratto = db.relationship("Contratto")
    struttura = db.relationship("Struttura")
    inputs = db.relationship("CedolinoInput", cascade="all, delete-orphan",
                             back_populates="cedolino")
    righe = db.relationship("CedolinoRiga", cascade="all, delete-orphan",
                            order_by="CedolinoRiga.sequenza", back_populates="cedolino")

    def input_map(self):
        return {i.codice: i.valore for i in self.inputs}

    def riga(self, codice):
        for r in self.righe:
            if r.codice == codice:
                return r
        return None

    def importo(self, codice):
        r = self.riga(codice)
        return r.importo if r else 0.0


class CedolinoInput(db.Model):
    __tablename__ = "cedolino_inputs"
    id = db.Column(db.Integer, primary_key=True)
    cedolino_id = db.Column(db.Integer, db.ForeignKey("cedolini.id", ondelete="CASCADE"), index=True)
    codice = db.Column(db.String(30), nullable=False)
    valore = db.Column(db.Float, default=0.0)

    cedolino = db.relationship("Cedolino", back_populates="inputs")


class CedolinoRiga(db.Model):
    __tablename__ = "cedolino_righe"
    id = db.Column(db.Integer, primary_key=True)
    cedolino_id = db.Column(db.Integer, db.ForeignKey("cedolini.id", ondelete="CASCADE"), index=True)
    sequenza = db.Column(db.Integer)
    codice = db.Column(db.String(30))
    nome = db.Column(db.String(160))
    categoria_codice = db.Column(db.String(20))
    categoria_tipo = db.Column(db.String(20))
    quantita = db.Column(db.Float)
    base = db.Column(db.Float)
    importo = db.Column(db.Float, default=0.0)
    stampa = db.Column(db.Boolean, default=True)
    registro = db.Column(db.String(40), default="")

    cedolino = db.relationship("Cedolino", back_populates="righe")


# Voci variabili che si possono inserire in un cedolino (come hr.payslip.input).
INPUT_CATALOGO = [
    ("STR25", "Ore straordinario feriale (maggiorazione 25%)", "ore"),
    ("STR50", "Ore straordinario festivo/notturno (maggiorazione 50%)", "ore"),
    ("ORE_ASS", "Ore di assenza non retribuita", "ore"),
    ("FERIE", "Ore di ferie godute", "ore"),
    ("ROL", "Ore di permesso (ROL) godute", "ore"),
    ("PREMIO", "Premio una tantum (lordo)", "€"),
    ("RIMBORSI", "Rimborsi spese documentati (non imponibili)", "€"),
    ("ANTICIPO", "Anticipo già erogato da recuperare", "€"),
    ("MESI_13", "Mesi maturati per la tredicesima", "mesi"),
]
INPUT_CODES = [c for c, _, _ in INPUT_CATALOGO]
