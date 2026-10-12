"""Punto di avvio: `python app.py` in locale, `gunicorn app:app` su Railway."""
import os

from masterpayroll import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=bool(os.environ.get("FLASK_DEBUG")))
