from app import models  # noqa: F401
from app.db.database import Base
from sqlalchemy import create_engine, inspect


def test_models_create_on_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"courses", "assessments", "resources", "sync_runs"}.issubset(tables)
