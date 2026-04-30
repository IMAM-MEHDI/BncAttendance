from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database.models import Base
from utils.config import settings

# Connection setup
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

# SQLite requires different arguments for multi-threading
connect_args = {"check_same_thread": False} if SQLALCHEMY_DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
