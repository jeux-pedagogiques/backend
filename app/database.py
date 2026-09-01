import os

from dotenv import load_dotenv
from sqlmodel import SQLModel, Session, create_engine

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = "sqlite:///./test.db"

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("postgresql://"):
    connect_args = {"connect_timeout": 10}
    if "neon.tech" in DATABASE_URL:
        connect_args["sslmode"] = "require"

    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20,
        connect_args=connect_args,
    )
else:
    engine = create_engine(DATABASE_URL, echo=False)


def create_db_and_tables():
    """Create all tables defined by SQLModel metadata."""
    try:
        SQLModel.metadata.create_all(engine)
        from sqlalchemy import text
        with engine.connect() as conn:
            try:
                conn.execute(text("ALTER TABLE module_analyses ADD COLUMN IF NOT EXISTS quiz_data JSON;"))
                conn.commit()
            except Exception:
                pass
    except Exception as e:
        print(f"Database table creation notice: {e}")


def get_session():
    """FastAPI dependency that yields a database session."""
    with Session(engine) as session:
        yield session
