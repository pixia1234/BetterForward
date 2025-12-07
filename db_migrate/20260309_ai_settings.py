import sqlite3


def upgrade(db_path):
    with sqlite3.connect(db_path) as conn:
        db_cursor = conn.cursor()
        # Ensure AI spam detection settings exist so they can be updated by admins
        db_cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('ai_api_key', NULL);
        """)
        db_cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('ai_api_base', NULL);
        """)
        db_cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('ai_model', 'gpt-3.5-turbo');
        """)
        conn.commit()
