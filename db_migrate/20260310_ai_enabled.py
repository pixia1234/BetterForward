import sqlite3


def upgrade(db_path):
    with sqlite3.connect(db_path) as conn:
        db_cursor = conn.cursor()
        db_cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('ai_enabled', 'enable');
        """)
        conn.commit()
