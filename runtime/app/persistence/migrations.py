from sqlalchemy import inspect

from app.persistence.database import Base, engine


def run_migrations() -> None:
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "agents" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("agents")}
    if "endpoint" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE agents ADD COLUMN endpoint VARCHAR(512)"
            )
