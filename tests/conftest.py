"""Shared pytest fixtures: in-memory SQLite session for repo tests."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from intel.storage.models import Base


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    sess = Session()
    try:
        yield sess
        sess.commit()
    finally:
        sess.close()
