import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "sqlite:///ai_supplier.db")

engine = create_engine(DB_PATH, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

# Ensure DB schema exists (idempotent)
from db import models  # noqa: E402
models.Base.metadata.create_all(bind=engine)

# --- lightweight auto-migrations for SQLite (add missing columns) ---
from sqlalchemy import inspect, text

def _ensure_columns():
    insp = inspect(engine)
    if engine.url.get_backend_name() != "sqlite":
        return  # only implemented for sqlite for now
    existing_cols = {col["name"] for col in insp.get_columns("suppliers")}
    app_cols = {col["name"] for col in insp.get_columns("applications")}
    alter_stmts = []
    if "website" not in existing_cols:
        alter_stmts.append("ALTER TABLE suppliers ADD COLUMN website VARCHAR;")
    if "whatsapp" not in existing_cols:
        alter_stmts.append("ALTER TABLE suppliers ADD COLUMN whatsapp VARCHAR;")
    if "city" not in existing_cols:
        alter_stmts.append("ALTER TABLE suppliers ADD COLUMN city VARCHAR;")

    # ensure applications.buyer_id and amocrm_id exist
    if "buyer_id" not in app_cols:
        alter_stmts.append("ALTER TABLE applications ADD COLUMN buyer_id INTEGER REFERENCES buyers(id);")
    if "amocrm_id" not in app_cols:
        alter_stmts.append("ALTER TABLE applications ADD COLUMN amocrm_id INTEGER;")
    with engine.begin() as conn:
        for stmt in alter_stmts:
            conn.execute(text(stmt))

_ensure_columns()

def get_session() -> Session:
    """Provide a transactional scope."""
    return SessionLocal()
