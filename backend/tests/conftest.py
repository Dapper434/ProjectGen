"""Points the whole test session at a throwaway SQLite file instead of the real
factoryos.db — must happen before config.py/database.py are first imported by
anything (including app.py, transitively), so this sets the env var at collection
time, ahead of any other import in the suite."""
import os
import tempfile

_tmp_db = tempfile.NamedTemporaryFile(prefix='factoryos_test_', suffix='.db', delete=False)
_tmp_db.close()
os.environ['DATABASE_URL'] = f'sqlite:///{_tmp_db.name}'
os.environ.setdefault('SECRET_KEY', 'test-secret-key')

import pytest  # noqa: E402

from database import Base, engine, db_session  # noqa: E402
import models  # noqa: E402,F401 -- registers every model on Base.metadata


@pytest.fixture(autouse=True)
def _fresh_schema():
    """Every test gets a clean, empty schema — cheap enough on SQLite that
    per-test isolation is simpler than per-test transactions/rollback."""
    Base.metadata.create_all(bind=engine)
    yield
    db_session.remove()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client_row():
    from models import Client
    c = Client(name='Acme Co', industry='Retail')
    db_session.add(c)
    db_session.flush()
    return c


@pytest.fixture
def engagement(client_row):
    from models import Engagement
    e = Engagement(client_id=client_row.id, status='awaiting_transcript')
    db_session.add(e)
    db_session.flush()
    return e
