import logging

from flask import Flask, render_template, Response
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SASession

from .models import SyncLog

logger = logging.getLogger(__name__)


def create_app(db_path: str) -> Flask:
    app = Flask(__name__)
    app.config["db_path"] = db_path

    @app.route("/")
    def index():
        engine = create_engine(f"sqlite:///{db_path}")
        with SASession(engine) as session:
            logs = (
                session.query(SyncLog)
                .order_by(SyncLog.id.desc())
                .limit(50)
                .all()
            )
        return render_template("log.html", logs=[l.to_dict() for l in logs])

    @app.route("/health")
    def health():
        engine = create_engine(f"sqlite:///{db_path}")
        try:
            with SASession(engine) as session:
                session.execute(text("SELECT 1"))
            return Response("OK", status=200)
        except Exception:
            return Response("DB error", status=500)

    return app
