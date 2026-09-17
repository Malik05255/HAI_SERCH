from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=2)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def ensure_schema() -> None:
    """Create tables and apply safe additive compatibility migrations.

    Both API and worker call this because Docker may start either process first.
    """
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS account_id VARCHAR(36) NULL")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_jobs_account_id ON jobs (account_id)")
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_error TEXT NULL")
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS context_text TEXT NOT NULL DEFAULT ''")
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS context_revision INTEGER NOT NULL DEFAULT 0")
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notification_pending BOOLEAN NOT NULL DEFAULT FALSE")
        connection.exec_driver_sql("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS notification_sent_at TIMESTAMPTZ NULL")
        connection.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_jobs_notification_pending ON jobs (notification_pending)")
        connection.exec_driver_sql("ALTER TABLE devices ADD COLUMN IF NOT EXISTS push_token TEXT NULL")
        connection.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS notification_deliveries (
                job_id VARCHAR(36) NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                device_id VARCHAR(36) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                state VARCHAR(16) NOT NULL DEFAULT 'pending',
                sent_at TIMESTAMPTZ NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (job_id, device_id)
            )
            """
        )
        connection.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_notification_deliveries_state ON notification_deliveries (state)"
        )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
