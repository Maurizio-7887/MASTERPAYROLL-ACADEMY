"""Blueprint «posta» — Posta in uscita (buste inviate per email).

Una cartella per attività: le pagine HTML sono in templates/posta/."""
from flask import Response, render_template, request
from ... import mailer
from ...models import MailMail
from ..comune import (ws_get, ws_query)

from ..comune import area

bp = area("posta")

STATE_FILTERS = [("draft", "Bozza"), ("verify", "Revisione in attesa"), ("done", "Completata"),
                 ("cancel", "Rifiutata")]

def _pdf_response(data, filename):
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@bp.route("/outbox")
def outbox():
    rows = ws_query(MailMail).order_by(MailMail.date.desc()).all()
    return render_template("posta/outbox.html", rows=rows, smtp=mailer.smtp_configured())


@bp.route("/outbox/<int:mail_id>")
def outbox_mail(mail_id):
    m = ws_get(MailMail, mail_id)
    if request.args.get("allegato"):
        return _pdf_response(m.attachment or b"", m.attachment_name or "allegato.pdf")
    return render_template("posta/outbox_mail.html", m=m)
