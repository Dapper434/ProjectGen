from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os

# `or` (not `.get(key, default)`) so a blank value in .env — e.g. `DATABASE_URL=` left
# empty after copying .env.example — falls back to the default instead of failing.
DATABASE_URL = os.environ.get('DATABASE_URL') or 'sqlite:///factoryos.db'

engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False,
                                         autoflush=False,
                                         bind=engine))

Base = declarative_base()
Base.query = db_session.query_property()

def init_db():
    import models
    Base.metadata.create_all(bind=engine)
