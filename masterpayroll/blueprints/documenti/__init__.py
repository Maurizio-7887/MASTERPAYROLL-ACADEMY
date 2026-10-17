"""Blueprint «documenti» — documenti del dipendente (modulo OCA hr_employee_document): contratto firmato,
giudizio di idoneità, attestati, documento d'identità. File fino a 5 MB salvati nel database dell'ambiente.

Una cartella per attività: le pagine HTML sono in templates/documenti/."""
import mimetypes

from flask import Response, abort, flash, g, redirect, render_template, request, url_for

from ... import payroll
from ...models import DocumentoDipendente, Employee, db
from ...scadenze import TIPI_DOCUMENTO
from ..comune import area, author, f_date, f_id, f_str, handle_user_error, ws_get, ws_query

bp = area("documenti")

MAX_BYTES = 5 * 1024 * 1024
ESTENSIONI = {".pdf", ".png", ".jpg", ".jpeg", ".txt", ".doc", ".docx", ".odt", ".xlsx"}


@bp.route("/documenti", methods=["GET", "POST"])
@handle_user_error
def elenco():
    if request.method == "POST":
        if g.ws_altrui:
            abort(403)
        e = ws_get(Employee, f_id("employee_id"))
        f = request.files.get("file")
        if not f or not f.filename:
            raise payroll.UserError("Scegli il file da caricare.")
        nomefile = f.filename.replace("\\", "/").split("/")[-1].replace('"', "").replace(";", "")[:200]
        est = ("." + nomefile.rsplit(".", 1)[-1].lower()) if "." in nomefile else ""
        if est not in ESTENSIONI:
            raise payroll.UserError("Formati ammessi: " + ", ".join(sorted(ESTENSIONI)) + ".")
        dati = f.read(MAX_BYTES + 1)
        if len(dati) > MAX_BYTES:
            raise payroll.UserError("Il file supera 5 MB.")
        d = DocumentoDipendente(workspace_id=g.ws.id, employee=e, tipo=f_str("tipo", "altro"),
                                nome=f_str("nome") or nomefile, filename=nomefile, contenuto=dati, dimensione=len(dati),
                                mimetype=mimetypes.guess_type(nomefile)[0] or "application/octet-stream",
                                scadenza=f_date("scadenza"), note=f_str("note"))
        db.session.add(d)
        payroll.log_message(g.ws.id, "hr.employee", e.id, author=author(), body=f"Caricato il documento «{d.nome}».")
        db.session.commit()
        flash(f"Documento «{d.nome}» caricato.", "success")
        return redirect(url_for("documenti.elenco", employee_id=e.id))
    emp_id = request.args.get("employee_id", type=int)
    q = ws_query(DocumentoDipendente)
    if emp_id:
        q = q.filter_by(employee_id=emp_id)
    docs = q.order_by(DocumentoDipendente.created_at.desc()).all()
    return render_template("documenti/elenco.html", docs=docs, emp_id=emp_id, tipi=TIPI_DOCUMENTO,
                           dipendenti=ws_query(Employee).order_by(Employee.last_name).all())


@bp.route("/documenti/<int:doc_id>/file")
def scarica(doc_id):
    d = ws_get(DocumentoDipendente, doc_id)
    nome = (d.filename or "").encode("ascii", "ignore").decode() or "documento"
    disp = "inline" if d.mimetype in ("application/pdf", "image/png", "image/jpeg", "text/plain") else "attachment"
    return Response(d.contenuto or b"", mimetype=d.mimetype,
                    headers={"Content-Disposition": f'{disp}; filename="{nome}"', "X-Content-Type-Options": "nosniff"})


@bp.route("/documenti/<int:doc_id>/elimina", methods=["POST"])
def elimina(doc_id):
    if g.ws_altrui:
        abort(403)
    d = ws_get(DocumentoDipendente, doc_id)
    emp_id = d.employee_id
    db.session.delete(d)
    db.session.commit()
    flash("Documento eliminato.", "success")
    return redirect(url_for("documenti.elenco", employee_id=emp_id))
