"""Modello linguistico facoltativo. Spento per default: si accende solo con LLM_API_KEY e LLM_MODEL impostati su Railway
(la chiave e il costo sono del docente; gli allievi non ne hanno bisogno). Fornitore: Anthropic (API Messages).

Regole: al modello si mandano solo testi di CCNL e domande generali, mai dati dei dipendenti; ogni chiamata si registra
nell'ambiente dell'allievo; c'è un tetto mensile di chiamate per allievo (LLM_LIMITE_MESE, default 30). Se il modello non
risponde, il laboratorio funziona lo stesso con il motore locale.
"""
import json
import os
import urllib.request
from datetime import date

API_URL = "https://api.anthropic.com/v1/messages"


def attivo():
    return bool(os.environ.get("LLM_API_KEY") and os.environ.get("LLM_MODEL"))


def limite_mese():
    try:
        return int(os.environ.get("LLM_LIMITE_MESE", "30"))
    except ValueError:
        return 30


def riformula(domanda, schede, registro):
    """Risposta in linguaggio naturale costruita SOLO sulle schede trovate. registro: lista (modificata sul posto) con le
    chiamate dell'allievo. Restituisce (testo, motivo) con testo None se il modello è spento, oltre il tetto o in errore."""
    if not attivo():
        return None, "modello linguistico non attivo"
    mese = date.today().strftime("%Y-%m")
    usate = sum(1 for r in registro if r.get("mese") == mese)
    if usate >= limite_mese():
        return None, f"tetto di {limite_mese()} chiamate nel mese raggiunto"
    contesto = "\n\n".join(f"[{i}] {s['contratto']} - {s['titolo']}: {s['testo']} (Fonte: {(s.get('fonte') or {}).get('sezione', '')}, "
                           f"p. {(s.get('fonte') or {}).get('pagina', '')})" for i, s in enumerate(schede, 1))
    prompt = ("Rispondi in italiano, in massimo 5 righe, alla domanda di un addetto paghe usando SOLO le schede seguenti. "
              "Cita tra parentesi il numero della scheda e l'articolo. Se le schede non bastano, dillo e non inventare.\n\n"
              f"Schede:\n{contesto}\n\nDomanda: {domanda}")
    body = json.dumps({"model": os.environ["LLM_MODEL"], "max_tokens": 400,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(API_URL, data=body, method="POST", headers={
        "x-api-key": os.environ["LLM_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        testo = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    except Exception as ex:  # rete, chiave errata, modello inesistente: si continua senza
        registro.append({"mese": mese, "domanda": domanda[:200], "esito": f"errore: {str(ex)[:120]}"})
        return None, "il modello non ha risposto"
    registro.append({"mese": mese, "domanda": domanda[:200], "esito": "ok"})
    return testo, "ok"
