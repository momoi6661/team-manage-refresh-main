"""Team 成员管理版所需的轻量 SQLite 兼容迁移。"""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def get_db_path() -> Path:
    from app.config import settings
    return Path(settings.database_url.split("///")[-1])


def column_exists(cursor, table_name: str, column_name: str) -> bool:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return column_name in {row[1] for row in cursor.fetchall()}


def table_exists(cursor, table_name: str) -> bool:
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None


def run_auto_migration() -> None:
    db_path = get_db_path()
    if not db_path.exists():
        return

    migrations: list[str] = []
    with sqlite3.connect(str(db_path)) as connection:
        cursor = connection.cursor()
        team_columns = {
            "refresh_token_encrypted": "TEXT",
            "id_token_encrypted": "TEXT",
            "session_token_encrypted": "TEXT",
            "client_id": "VARCHAR(100)",
            "error_count": "INTEGER DEFAULT 0",
            "account_role": "VARCHAR(50)",
            "device_code_auth_enabled": "BOOLEAN DEFAULT 0",
            "pool_type": "VARCHAR(20) DEFAULT 'normal'",
        }
        if table_exists(cursor, "teams"):
            for name, declaration in team_columns.items():
                if not column_exists(cursor, "teams", name):
                    cursor.execute(f"ALTER TABLE teams ADD COLUMN {name} {declaration}")
                    migrations.append(f"teams.{name}")

        if not table_exists(cursor, "team_email_mappings"):
            cursor.execute("""
                CREATE TABLE team_email_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    team_id INTEGER NOT NULL,
                    email VARCHAR(255) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'invited',
                    source VARCHAR(20) NOT NULL DEFAULT 'sync',
                    last_seen_at DATETIME,
                    missing_sync_count INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
                )
            """)
            migrations.append("team_email_mappings")
        elif not column_exists(cursor, "team_email_mappings", "missing_sync_count"):
            cursor.execute("ALTER TABLE team_email_mappings ADD COLUMN missing_sync_count INTEGER NOT NULL DEFAULT 0")
            migrations.append("team_email_mappings.missing_sync_count")

        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_team_email_unique ON team_email_mappings (team_id, email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_email_email ON team_email_mappings (email)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_team_email_status ON team_email_mappings (team_id, status)")

    if migrations:
        logger.info("数据库迁移完成: %s", ", ".join(migrations))
