from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ...models import User

bp = Blueprint("accesso", __name__, template_folder="templates")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("cruscotto.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        user = User.query.filter_by(username=username).first()
        if user and user.is_active and user.check_password(request.form.get("password", "")):
            login_user(user)
            session.pop("ws_view", None)
            nxt = request.args.get("next")
            if nxt and nxt.startswith("/") and not nxt.startswith("//"):
                return redirect(nxt)
            return redirect(url_for("cruscotto.dashboard"))
        flash("Utente o password non validi.", "danger")
    return render_template("accesso/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("accesso.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def cambia_password():
    if request.method == "POST":
        old = request.form.get("old", "")
        new = request.form.get("new", "")
        if not current_user.check_password(old):
            flash("Password attuale errata.", "danger")
        elif len(new) < 6:
            flash("La nuova password deve avere almeno 6 caratteri.", "danger")
        else:
            from ...models import db
            current_user.set_password(new)
            db.session.commit()
            flash("Password aggiornata.", "success")
            return redirect(url_for("cruscotto.dashboard"))
    return render_template("accesso/password.html")
