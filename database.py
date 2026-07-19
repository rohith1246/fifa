import os
from typing import Generator
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Load env variables
load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///smart_stadium.db")

# Resolve Render legacy schema if postgres is used
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Configure engine
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,  # Verify connection health before use
        pool_recycle=3600,  # Recycle connections after 1 hour to prevent stale handles
        pool_size=5,  # Maintain 5 persistent worker connections
        max_overflow=10,  # Allow up to 10 overflow connections during traffic spikes
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """
    SQLAlchemy database session generator dependency.
    Yields:
        Session: Active database session connection.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
