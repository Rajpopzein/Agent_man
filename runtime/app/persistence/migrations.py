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
    if "context" not in columns:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE agents ADD COLUMN context TEXT NOT NULL DEFAULT ''"
            )

    table_names = inspector.get_table_names()
    if "agent_task_history" in table_names:
        history_columns = {
            column["name"]
            for column in inspector.get_columns("agent_task_history")
        }
        if "room_id" not in history_columns:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE agent_task_history "
                    "ADD COLUMN room_id VARCHAR(36)"
                )
                connection.exec_driver_sql(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_agent_task_history_room_id "
                    "ON agent_task_history (room_id)"
                )
