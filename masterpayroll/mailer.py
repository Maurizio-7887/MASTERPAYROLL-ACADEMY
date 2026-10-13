"""Invio della busta paga per email (mail_template_hr_payslip di Odoo).

Se le variabili SMTP non sono configurate l'email viene solo registrata nella
"Posta in uscita" (stato 'simulata'): in aula nessuno riceve email vere.
Variabili: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD, SMTP_FROM.
"""
import os
import smtplib
from html import escape
from email.message import EmailMessage

from . import reports
from .models import MailMail, db
from .payroll import log_message


def smtp_configured():
    return bool(os.environ.get("SMTP_HOST"))


def send_payslip(ws, slip, author=""):
    emp = slip.employee
    to = emp.work_email or emp.private_email
    periodo = slip.payslip_run.name if slip.payslip_run else slip.date_from.strftime("%m/%Y")
    subject = f"Busta paga {periodo} - {ws.name}"
    body = (f"<p>Gentile {escape(emp.first_name)} {escape(emp.last_name)},</p>"
            f"<p>in allegato trovi la busta paga di {escape(periodo)}.</p>"
            f"<p>Per qualsiasi domanda non esitare a contattarci.</p><p>{escape(author)}<br>{escape(ws.name)}</p>")
    pdf = reports.payslip_pdf(ws, [slip])
    fname = f"busta_{(slip.number or str(slip.id)).replace('/', '_')}.pdf"
    mail = MailMail(workspace_id=ws.id, payslip_id=slip.id, email_from=os.environ.get("SMTP_FROM", ws.email),
                    email_to=to or "", subject=subject, body_html=body, attachment_name=fname, attachment=pdf)
    if not to:
        mail.state, mail.failure_reason = "exception", "Il dipendente non ha un indirizzo email."
    elif smtp_configured():
        try:
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = subject, mail.email_from, to
            msg.set_content("Busta paga in allegato.")
            msg.add_alternative(body, subtype="html")
            msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=fname)
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", 587)), timeout=20) as s:
                s.starttls()
                if os.environ.get("SMTP_USER"):
                    s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
            mail.state = "sent"
        except (OSError, smtplib.SMTPException) as exc:
            mail.state, mail.failure_reason = "exception", str(exc)
    else:
        mail.state = "simulated"
    db.session.add(mail)
    log_message(ws.id, "hr.payslip", slip.id, body=f"Email «{subject}» a {to or '—'} ({mail.state})",
                author=author, message_type="email")
    return mail.state in ("sent", "simulated")
