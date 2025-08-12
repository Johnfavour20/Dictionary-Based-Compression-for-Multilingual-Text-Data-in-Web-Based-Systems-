#!/usr/bin/env python3
"""
Database Initialization Script for Multilingual Text Compression Tool
"""
import os
import sys
import sqlite3
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

def create_database_safely():
    """Create SQLite database with error handling"""
    try:
        db_name = os.getenv("DB_NAME", "multilingual_compression.db")
        print(f"📊 Creating/connecting to database: {db_name}")
        
        conn = sqlite3.connect(db_name)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        
        print(f"✅ Database '{db_name}' ready")
        conn.close()
        return True
        
    except sqlite3.Error as err:
        print(f"❌ Failed to create database: {err}")
        return False

def create_tables_step_by_step():
    """Create tables and indexes one by one with error handling"""
    try:
        db_name = os.getenv("DB_NAME", "multilingual_compression.db")
        conn = sqlite3.connect(db_name)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        tables = {
            "users": """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    registration_date TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_login TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """,
            "files": """
                CREATE TABLE IF NOT EXISTS files (
                    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    original_size INTEGER NOT NULL,
                    file_encoding TEXT DEFAULT 'utf-8',
                    file_type TEXT DEFAULT 'txt',
                    upload_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """,
            "compression_results": """
                CREATE TABLE IF NOT EXISTS compression_results (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id INTEGER NOT NULL,
                    compressed_size INTEGER NOT NULL,
                    compression_ratio REAL NOT NULL,
                    compression_time REAL NOT NULL,
                    algorithm_used TEXT DEFAULT 'lzw77',
                    compressed_file_path TEXT,
                    session_id TEXT,
                    date_processed TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
                )
            """,
            "logs": """
                CREATE TABLE IF NOT EXISTS logs (
                    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT CHECK(status IN ('SUCCESS', 'FAILED', 'WARNING')) DEFAULT 'SUCCESS',
                    details TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE SET NULL
                )
            """,
            "system_stats": """
                CREATE TABLE IF NOT EXISTS system_stats (
                    stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stat_date TEXT NOT NULL,
                    total_users INTEGER DEFAULT 0,
                    total_files_processed INTEGER DEFAULT 0,
                    total_bytes_compressed INTEGER DEFAULT 0,
                    total_bytes_saved INTEGER DEFAULT 0,
                    average_compression_ratio REAL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (stat_date)
                )
            """,
            "user_preferences": """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    preference_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    preference_name TEXT NOT NULL,
                    preference_value TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                    UNIQUE (user_id, preference_name)
                )
            """
        }
        
        indexes = {
            "users": [
                "CREATE INDEX IF NOT EXISTS idx_username ON users(username)",
                "CREATE INDEX IF NOT EXISTS idx_email ON users(email)",
                "CREATE INDEX IF NOT EXISTS idx_registration_date ON users(registration_date)"
            ],
            "files": [
                "CREATE INDEX IF NOT EXISTS idx_user_id ON files(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_upload_time ON files(upload_time)",
                "CREATE INDEX IF NOT EXISTS idx_file_name ON files(file_name)"
            ],
            "compression_results": [
                "CREATE INDEX IF NOT EXISTS idx_file_id ON compression_results(file_id)",
                "CREATE INDEX IF NOT EXISTS idx_session_id ON compression_results(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_date_processed ON compression_results(date_processed)",
                "CREATE INDEX IF NOT EXISTS idx_algorithm ON compression_results(algorithm_used)"
            ],
            "logs": [
                "CREATE INDEX IF NOT EXISTS idx_user_id ON logs(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp)",
                "CREATE INDEX IF NOT EXISTS idx_action ON logs(action)",
                "CREATE INDEX IF NOT EXISTS idx_status ON logs(status)"
            ],
            "system_stats": [
                "CREATE INDEX IF NOT EXISTS idx_stat_date ON system_stats(stat_date)"
            ],
            "user_preferences": [
                "CREATE INDEX IF NOT EXISTS idx_user_id ON user_preferences(user_id)"
            ]
        }
        
        triggers = {
            "update_system_stats": """
                CREATE TRIGGER IF NOT EXISTS update_system_stats
                AFTER INSERT ON compression_results
                FOR EACH ROW
                BEGIN
                    INSERT OR REPLACE INTO system_stats (
                        stat_date,
                        total_users,
                        total_files_processed,
                        total_bytes_compressed,
                        total_bytes_saved,
                        average_compression_ratio,
                        updated_at
                    )
                    SELECT
                        date('now'),
                        (SELECT COUNT(*) FROM users),
                        (SELECT COUNT(*) FROM files),
                        (SELECT SUM(compressed_size) FROM compression_results),
                        (SELECT SUM(f.original_size - cr.compressed_size) FROM compression_results cr JOIN files f ON cr.file_id = f.file_id),
                        (SELECT AVG(compression_ratio) FROM compression_results),
                        CURRENT_TIMESTAMP;
                END;
            """
        }
        
        # Create tables
        for table_name, table_sql in tables.items():
            try:
                print(f"📋 Creating table: {table_name}")
                cursor.execute(table_sql)
                conn.commit()
                print(f"✅ Table '{table_name}' created successfully")
            except sqlite3.Error as err:
                print(f"⚠️ Warning creating table '{table_name}': {err}")
                if "already exists" not in str(err).lower():
                    conn.close()
                    return False
        
        # Create indexes
        for table_name, index_list in indexes.items():
            for index_sql in index_list:
                try:
                    print(f"📋 Creating index for {table_name}: {index_sql}")
                    cursor.execute(index_sql)
                    conn.commit()
                    print(f"✅ Index created successfully")
                except sqlite3.Error as err:
                    print(f"⚠️ Warning creating index for '{table_name}': {err}")
                    if "already exists" not in str(err).lower():
                        conn.close()
                        return False
        
        # Create triggers
        for trigger_name, trigger_sql in triggers.items():
            try:
                print(f"📋 Creating trigger: {trigger_name}")
                cursor.execute(trigger_sql)
                conn.commit()
                print(f"✅ Trigger '{trigger_name}' created successfully")
            except sqlite3.Error as err:
                print(f"⚠️ Warning creating trigger '{trigger_name}': {err}")
                if "already exists" not in str(err).lower():
                    conn.close()
                    return False
        
        # Initialize system_stats
        cursor.execute("""
            INSERT OR IGNORE INTO system_stats (stat_date, total_users, total_files_processed, total_bytes_compressed, total_bytes_saved, average_compression_ratio)
            VALUES (?, 0, 0, 0, 0, 0)
        """, (datetime.now().strftime('%Y-%m-%d'),))
        conn.commit()
        
        conn.close()
        return True
        
    except sqlite3.Error as err:
        print(f"❌ Failed to create tables or indexes: {err}")
        return False

def create_views_safely():
    """Create views with error handling"""
    try:
        db_name = os.getenv("DB_NAME", "multilingual_compression.db")
        conn = sqlite3.connect(db_name)
        conn.execute("PRAGMA foreign_keys = ON")
        cursor = conn.cursor()
        
        views = {
            "user_compression_stats": """
                CREATE VIEW IF NOT EXISTS user_compression_stats AS
                SELECT 
                    u.user_id,
                    u.username,
                    u.email,
                    COUNT(DISTINCT f.file_id) as total_files,
                    COALESCE(SUM(f.original_size), 0) as total_original_size,
                    COALESCE(SUM(cr.compressed_size), 0) as total_compressed_size,
                    COALESCE(SUM(f.original_size - cr.compressed_size), 0) as total_space_saved,
                    COALESCE(AVG(cr.compression_ratio), 0) as avg_compression_ratio,
                    COALESCE(AVG(cr.compression_time), 0) as avg_compression_time,
                    MAX(cr.date_processed) as last_compression_date
                FROM users u
                LEFT JOIN files f ON u.user_id = f.user_id
                LEFT JOIN compression_results cr ON f.file_id = cr.file_id
                GROUP BY u.user_id, u.username, u.email
            """,
            "file_compression_details": """
                CREATE VIEW IF NOT EXISTS file_compression_details AS
                SELECT 
                    f.file_id,
                    f.user_id,
                    u.username,
                    f.file_name,
                    f.original_size,
                    f.file_encoding,
                    f.file_type,
                    f.upload_time,
                    cr.result_id,
                    cr.compressed_size,
                    cr.compression_ratio,
                    cr.compression_time,
                    cr.algorithm_used,
                    cr.session_id,
                    cr.date_processed,
                    (f.original_size - cr.compressed_size) as space_saved
                FROM files f
                JOIN users u ON f.user_id = f.user_id
                JOIN compression_results cr ON f.file_id = cr.file_id
            """,
            "recent_activity": """
                CREATE VIEW IF NOT EXISTS recent_activity AS
                SELECT 
                    'compression' as activity_type,
                    u.username,
                    f.file_name as activity_description,
                    cr.date_processed as activity_time,
                    cr.compression_ratio,
                    f.original_size,
                    cr.compressed_size
                FROM files f
                JOIN users u ON f.user_id = f.user_id
                JOIN compression_results cr ON f.file_id = cr.file_id
                WHERE cr.date_processed >= date('now', '-30 days')
                UNION ALL
                SELECT 
                    'decompression' as activity_type,
                    u.username,
                    'Decompressed file' as activity_description,
                    l.timestamp as activity_time,
                    NULL as compression_ratio,
                    NULL as original_size,
                    NULL as compressed_size
                FROM logs l
                JOIN users u ON l.user_id = u.user_id
                WHERE l.action = 'FILE_DECOMPRESSION' 
                  AND l.timestamp >= date('now', '-30 days')
                  AND l.status = 'SUCCESS'
                UNION ALL
                SELECT 
                    'login' as activity_type,
                    u.username,
                    'User login' as activity_description,
                    l.timestamp as activity_time,
                    NULL as compression_ratio,
                    NULL as original_size,
                    NULL as compressed_size
                FROM logs l
                JOIN users u ON l.user_id = u.user_id
                WHERE l.action = 'USER_LOGIN' 
                  AND l.timestamp >= date('now', '-30 days')
                  AND l.status = 'SUCCESS'
                ORDER BY activity_time DESC
                LIMIT 100
            """
        }
        
        for view_name, view_sql in views.items():
            try:
                print(f"🔍 Creating view: {view_name}")
                cursor.execute(view_sql)
                conn.commit()
                print(f"✅ View '{view_name}' created successfully")
            except sqlite3.Error as err:
                print(f"⚠️ Warning creating view '{view_name}': {err}")
        
        conn.close()
        return True
        
    except sqlite3.Error as err:
        print(f"❌ Failed to create views: {err}")
        return False

def verify_database_setup():
    """Verify that the database was set up correctly"""
    try:
        db_name = os.getenv("DB_NAME", "multilingual_compression.db")
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        
        print(f"📊 Database verification:")
        print(f"   Tables created: {len(tables)}")
        
        for table in tables:
            print(f"   ✓ {table[0]}")
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        triggers = cursor.fetchall()
        print(f"   Triggers created: {len(triggers)}")
        for trigger in triggers:
            print(f"   ✓ {trigger[0]}")
        
        conn.close()
        return len(tables) > 0
        
    except sqlite3.Error as err:
        print(f"❌ Database verification failed: {err}")
        return False

def reset_database():
    """Drop and recreate the database to resolve conflicts"""
    try:
        db_name = os.getenv("DB_NAME", "multilingual_compression.db")
        if os.path.exists(db_name):
            print(f"🗑️ Dropping existing database: {db_name}")
            os.remove(db_name)
        return create_database_safely() and create_tables_step_by_step() and create_views_safely()
    except Exception as err:
        print(f"❌ Failed to reset database: {err}")
        return False

def main():
    """Main function to set up the database"""
    print("🚀 Multilingual Text Compression - Database Setup")
    print("=" * 60)
    
    if not os.path.exists('.env'):
        print("❌ .env file not found!")
        print("📝 Please create a .env file with:")
        print("DB_NAME=multilingual_compression.db")
        return False
    
    load_dotenv()
    
    print(f"📋 Configuration:")
    print(f"   Database: {os.getenv('DB_NAME', 'not set')}")
    print()
    
    # Try creating database normally
    if create_database_safely() and create_tables_step_by_step() and create_views_safely():
        if verify_database_setup():
            print("\n🎉 Database setup completed successfully!")
            print("✅ Your database is ready for the Flask application")
            print("🚀 Next step: Run 'python app.py' to start your application")
            return True
    
    # If setup fails, try resetting the database
    print("\n⚠️ Initial setup failed, attempting to reset database...")
    if reset_database() and verify_database_setup():
        print("\n🎉 Database reset and setup completed successfully!")
        print("✅ Your database is ready for the Flask application")
        print("🚀 Next step: Run 'python app.py' to start your application")
        return True
    
    print("\n❌ Database setup failed")
    return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)