import os

from dotenv import load_dotenv
from sqlmodel import SQLModel, Session, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./test.db"

if DATABASE_URL.startswith("postgresql://") and "neon.tech" in DATABASE_URL:
    engine = create_engine(DATABASE_URL, echo=True, connect_args={"sslmode": "require"})
else:
    engine = create_engine(DATABASE_URL, echo=True)


def create_db_and_tables():
    """Create all tables defined by SQLModel metadata."""
    SQLModel.metadata.create_all(engine)
    
    # Automatically add quiz_data column if it doesn't exist
    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE module_analyses ADD COLUMN IF NOT EXISTS quiz_data JSON;"))
            conn.commit()
        except Exception:
            pass


def get_session():
    """FastAPI dependency that yields a database session."""
    with Session(engine) as session:
        yield session
