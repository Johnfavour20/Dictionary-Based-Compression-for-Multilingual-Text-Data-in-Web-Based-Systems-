import os
import sys
import time
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import sqlite3
from dotenv import load_dotenv
import bcrypt
import logging
import uuid
import zipfile
from compression_engine import HybridLZW77Compressor

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# Flask config
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "fallback-secret-key")
app.config['JWT_SECRET_KEY'] = os.getenv("JWT_SECRET_KEY", "fallback-jwt-secret")
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = int(os.getenv("JWT_EXPIRES_HOURS", 24)) * 3600

jwt = JWTManager(app)

# Setup logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.getenv('LOG_FILE', 'app.log')),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.db_name = os.getenv("DB_NAME", "multilingual_compression.db")
    
    def get_connection(self):
        """Get a database connection"""
        try:
            conn = sqlite3.connect(self.db_name)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as err:
            logger.error(f"Database connection error: {err}")
            return None
    
    def execute_script_from_file(self, script_content):
        """Execute the database initialization script"""
        try:
            conn = self.get_connection()
            if not conn:
                return False
            cursor = conn.cursor()
            
            statements = [stmt.strip() for stmt in script_content.split(';') if stmt.strip()]
            
            for statement in statements:
                if statement and not statement.startswith('--'):
                    try:
                        cursor.execute(statement)
                        conn.commit()
                    except sqlite3.Error as err:
                        if "already exists" not in str(err).lower():
                            logger.warning(f"Statement execution warning: {err}")
                            logger.warning(f"Statement: {statement[:100]}...")
            
            cursor.close()
            conn.close()
            logger.info("Database schema initialized successfully")
            return True
            
        except sqlite3.Error as err:
            logger.error(f"Failed to execute database script: {err}")
            return False
    
    def log_action(self, user_id, action, status='SUCCESS', details=None, ip_address=None, user_agent=None):
        """Log user actions to the logs table"""
        try:
            conn = self.get_connection()
            if conn:
                cursor = conn.cursor()
                # Allow null user_id for logs (as per schema)
                cursor.execute("""
                    INSERT INTO logs (user_id, action, status, details, ip_address, user_agent)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (user_id, action, status, details, ip_address, user_agent))
                conn.commit()
                cursor.close()
                conn.close()
        except Exception as e:
            logger.error(f"Failed to log action: {e}")
    
    def cleanup_old_data(self, days_old=30):
        """Remove old files and database entries"""
        try:
            conn = self.get_connection()
            if not conn:
                return False
            cursor = conn.cursor()
            cursor.execute("""
                SELECT compressed_file_path FROM compression_results 
                WHERE file_id IN (
                    SELECT file_id FROM files 
                    WHERE upload_time < date('now', ?)
                )
            """, (f'-{days_old} days',))
            paths = [row['compressed_file_path'] for row in cursor.fetchall()]
            for path in paths:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError as e:
                        logger.error(f"Failed to delete file {path}: {e}")
            cursor.execute("""
                DELETE FROM compression_results 
                WHERE file_id IN (
                    SELECT file_id FROM files 
                    WHERE upload_time < date('now', ?)
                )
            """, (f'-{days_old} days',))
            cursor.execute("""
                DELETE FROM files 
                WHERE upload_time < date('now', ?)
            """, (f'-{days_old} days',))
            cursor.execute("""
                DELETE FROM logs 
                WHERE timestamp < date('now', ?)
            """, (f'-{days_old} days',))
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            return False

    def verify_user(self, user_id):
        """Verify if user_id exists in users table"""
        try:
            conn = self.get_connection()
            if not conn:
                return False
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE user_id = ? AND is_active = 1", (user_id,))
            user = cursor.fetchone()
            cursor.close()
            conn.close()
            return bool(user)
        except Exception as e:
            logger.error(f"User verification error: {e}")
            return False

# Initialize database manager
db_manager = DatabaseManager()

def create_upload_directories():
    """Create necessary directories for file uploads"""
    directories = [
        os.getenv("UPLOAD_FOLDER", "uploads"),
        os.getenv("COMPRESSED_FOLDER", "compressed")
    ]
    
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            logger.info(f"Created directory: {directory}")

def hash_password(password):
    """Secure password hashing with bcrypt"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hash_password):
    """Verify password against bcrypt hash"""
    return bcrypt.checkpw(password.encode(), hash_password.encode())

@app.route('/')
@app.route('/index.html')
def serve_frontend():
    """Serve the frontend"""
    return send_from_directory('.', 'index.html')

@app.route('/api/register', methods=['POST'])
def register():
    """User registration endpoint"""
    try:
        data = request.get_json()
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        
        if not all([username, email, password]):
            return jsonify({"error": "Username, email, and password are required"}), 400
        
        conn = db_manager.get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        
        cursor.execute("SELECT user_id FROM users WHERE username = ? OR email = ?", (username, email))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return jsonify({"error": "Username or email already exists"}), 409
        
        password_hash = hash_password(password)
        cursor.execute("""
            INSERT INTO users (username, email, password_hash)
            VALUES (?, ?, ?)
        """, (username, email, password_hash))
        
        user_id = cursor.lastrowid
        if user_id is None:
            conn.rollback()
            cursor.close()
            conn.close()
            return jsonify({"error": "Failed to create user record"}), 500
            
        conn.commit()
        
        default_prefs = [
            ('default_algorithm', 'lzw77'),
            ('default_encoding', 'utf-8')
        ]
        
        for pref_name, pref_value in default_prefs:
            cursor.execute("""
                INSERT INTO user_preferences (user_id, preference_name, preference_value)
                VALUES (?, ?, ?)
            """, (user_id, pref_name, pref_value))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        db_manager.log_action(
            user_id, 
            'USER_REGISTRATION', 
            'SUCCESS', 
            f'New user registered: {username}',
            request.remote_addr,
            request.user_agent.string
        )
        
        return jsonify({
            "message": "User registered successfully",
            "user_id": user_id,
            "username": username
        }), 201
        
    except Exception as e:
        logger.error(f"Registration error: {e}")
        return jsonify({"error": "Registration failed"}), 500

@app.route('/api/login', methods=['POST'])
def login():
    """User login endpoint"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not all([username, password]):
            return jsonify({"error": "Username and password are required"}), 400
        
        conn = db_manager.get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, username, email, password_hash, is_active
            FROM users 
            WHERE username = ? OR email = ?
        """, (username, username))
        
        user = cursor.fetchone()
        
        if not user or not user['is_active']:
            cursor.close()
            conn.close()
            db_manager.log_action(
                None, 
                'USER_LOGIN', 
                'FAILED', 
                f'Login attempt for non-existent/inactive user: {username}',
                request.remote_addr,
                request.user_agent.string
            )
            return jsonify({"error": "Invalid credentials"}), 401
        
        if not verify_password(password, user['password_hash']):
            cursor.close()
            conn.close()
            db_manager.log_action(
                user['user_id'], 
                'USER_LOGIN', 
                'FAILED', 
                'Invalid password',
                request.remote_addr,
                request.user_agent.string
            )
            return jsonify({"error": "Invalid credentials"}), 401
        
        cursor.execute("UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE user_id = ?", (user['user_id'],))
        conn.commit()
        cursor.close()
        conn.close()
        
        access_token = create_access_token(identity=user['user_id'])
        
        db_manager.log_action(
            user['user_id'], 
            'USER_LOGIN', 
            'SUCCESS', 
            f'User logged in: {user["username"]}',
            request.remote_addr,
            request.user_agent.string
        )
        
        return jsonify({
            "message": "Login successful",
            "access_token": access_token,
            "user": {
                "user_id": user['user_id'],
                "username": user['username'],
                "email": user['email']
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"error": "Login failed"}), 500

@app.route('/api/profile', methods=['GET'])
@jwt_required()
def get_profile():
    """Get user profile and statistics"""
    try:
        user_id = get_jwt_identity()
        
        if not db_manager.verify_user(user_id):
            return jsonify({"error": "User not found or inactive"}), 404
        
        conn = db_manager.get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM user_compression_stats WHERE user_id = ?", (user_id,))
        stats = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if not stats:
            return jsonify({"error": "User stats not found"}), 404
        
        stats_dict = dict(stats)
        return jsonify({"user_stats": stats_dict}), 200
        
    except Exception as e:
        logger.error(f"Profile fetch error: {e}")
        return jsonify({"error": "Failed to fetch profile"}), 500

@app.route('/api/recent-activity', methods=['GET'])
@jwt_required()
def get_recent_activity():
    """Get recent user activity"""
    try:
        user_id = get_jwt_identity()
        
        if not db_manager.verify_user(user_id):
            return jsonify({"error": "User not found or inactive"}), 404
        
        conn = db_manager.get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM recent_activity 
            WHERE username = (SELECT username FROM users WHERE user_id = ?)
            ORDER BY activity_time DESC 
            LIMIT 20
        """, (user_id,))
        
        activities = [dict(row) for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return jsonify({"activities": activities}), 200
        
    except Exception as e:
        logger.error(f"Recent activity fetch error: {e}")
        return jsonify({"error": "Failed to fetch recent activity"}), 500

@app.route('/api/system-stats', methods=['GET'])
def get_system_stats():
    """Get system-wide statistics"""
    try:
        conn = db_manager.get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM system_stats 
            ORDER BY stat_date DESC 
            LIMIT 7
        """)
        
        stats = [dict(row) for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return jsonify({"system_stats": stats}), 200
        
    except Exception as e:
        logger.error(f"System stats fetch error: {e}")
        return jsonify({"error": "Failed to fetch system stats"}), 500

@app.route('/api/compress', methods=['POST'])
@jwt_required()
def compress():
    """Compress uploaded files using HybridLZW77Compressor"""
    user_id = get_jwt_identity()
    
    # Verify user exists before any operation
    if not db_manager.verify_user(user_id):
        db_manager.log_action(
            user_id,
            'FILE_COMPRESSION',
            'FAILED',
            'Invalid or inactive user',
            request.remote_addr,
            request.user_agent.string
        )
        return jsonify({"error": "User not found or inactive"}), 404

    try:
        files = request.files.getlist('files')
        algorithm = request.form.get('algorithm', 'lzw77')
        encoding = request.form.get('encoding', 'utf-8')
        
        if not files:
            return jsonify({"error": "No files uploaded"}), 400
        
        if encoding not in ['utf-8', 'utf-16', 'latin-1']:
            return jsonify({"error": "Unsupported encoding. Use utf-8, utf-16, or latin-1"}), 400
        
        upload_folder = os.getenv("UPLOAD_FOLDER", "uploads")
        compressed_folder = os.getenv("COMPRESSED_FOLDER", "compressed")
        session_id = str(uuid.uuid4())
        
        total_original_size = 0
        total_compressed_size = 0
        total_processing_time = 0
        compressed_files = []
        
        conn = db_manager.get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        compressor = HybridLZW77Compressor(encoding=encoding)
        
        for file in files:
            if file.filename == '':
                continue
                
            if not (file.mimetype == 'text/plain' or file.filename.endswith(('.txt', '.md', '.csv'))):
                continue
                
            # Save original file
            original_path = os.path.join(upload_folder, file.filename)
            file.save(original_path)
            original_size = os.path.getsize(original_path)
            total_original_size += original_size
            
            # Read file content as text
            try:
                with open(original_path, 'r', encoding=encoding) as f:
                    text = f.read()
            except UnicodeDecodeError:
                cursor.close()
                conn.close()
                return jsonify({"error": f"File {file.filename} is not valid {encoding} text"}), 400
            
            # Compress using LZW77
            start_time = time.time()
            compressed_data = compressor.compress(text)
            processing_time = time.time() - start_time
            
            # Save compressed file
            compressed_filename = f"compressed_{session_id}_{file.filename}.lzw"
            compressed_path = os.path.join(compressed_folder, compressed_filename)
            with open(compressed_path, 'wb') as f_out:
                f_out.write(compressed_data)
            
            compressed_size = os.path.getsize(compressed_path)
            stats = compressor.get_compression_stats(text, compressed_data)
            compression_ratio = stats['compression_ratio']
            
            total_compressed_size += compressed_size
            total_processing_time += processing_time
            compressed_files.append(compressed_path)
            
            # Insert file metadata
            try:
                cursor.execute("""
                    INSERT INTO files (user_id, file_name, original_size, file_encoding, file_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (user_id, file.filename, original_size, encoding, file.filename.split('.')[-1]))
                file_id = cursor.lastrowid
            except sqlite3.Error as e:
                cursor.close()
                conn.close()
                logger.error(f"Error inserting into files: {e}")
                return jsonify({"error": f"Database error: {str(e)}"}), 500
            
            # Insert compression results
            try:
                cursor.execute("""
                    INSERT INTO compression_results (
                        file_id, compressed_size, compression_ratio, compression_time, 
                        algorithm_used, compressed_file_path, session_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    file_id, compressed_size, compression_ratio, processing_time,
                    algorithm, compressed_path, session_id
                ))
            except sqlite3.Error as e:
                cursor.close()
                conn.close()
                logger.error(f"Error inserting into compression_results: {e}")
                return jsonify({"error": f"Database error: {str(e)}"}), 500
            
            conn.commit()
        
        # Create zip file
        zip_path = os.path.join(compressed_folder, f"{session_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for compressed_path in compressed_files:
                zipf.write(compressed_path, os.path.basename(compressed_path))
        
        cursor.close()
        conn.close()
        
        db_manager.log_action(
            user_id,
            'FILE_COMPRESSION',
            'SUCCESS',
            f'Compressed {len(files)} files with {algorithm} (encoding: {encoding})',
            request.remote_addr,
            request.user_agent.string
        )
        
        download_url = f"/compressed/{session_id}.zip"
        
        return jsonify({
            "message": "Compression successful",
            "original_size": total_original_size,
            "compressed_size": total_compressed_size,
            "compression_ratio": ((total_original_size - total_compressed_size) / total_original_size * 100) if total_original_size > 0 else 0,
            "processing_time": round(total_processing_time, 3),
            "download_url": download_url
        }), 200
        
    except Exception as e:
        logger.error(f"Compression error: {e}")
        db_manager.log_action(
            user_id,
            'FILE_COMPRESSION',
            'FAILED',
            f'Compression failed: {str(e)}',
            request.remote_addr,
            request.user_agent.string
        )
        return jsonify({"error": f"Compression failed: {str(e)}"}), 500

@app.route('/api/decompress', methods=['POST'])
@jwt_required()
def decompress():
    """Decompress uploaded .lzw files"""
    user_id = get_jwt_identity()
    
    # Verify user exists before any operation
    if not db_manager.verify_user(user_id):
        db_manager.log_action(
            user_id,
            'FILE_DECOMPRESSION',
            'FAILED',
            'Invalid or inactive user',
            request.remote_addr,
            request.user_agent.string
        )
        return jsonify({"error": "User not found or inactive"}), 404

    try:
        files = request.files.getlist('files')
        encoding = request.form.get('encoding', 'utf-8')
        
        if not files:
            return jsonify({"error": "No files uploaded"}), 400
        
        if encoding not in ['utf-8', 'utf-16', 'latin-1']:
            return jsonify({"error": "Unsupported encoding. Use utf-8, utf-16, or latin-1"}), 400
        
        compressed_folder = os.getenv("COMPRESSED_FOLDER", "compressed")
        session_id = str(uuid.uuid4())
        
        decompressed_files = []
        conn = db_manager.get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        compressor = HybridLZW77Compressor(encoding=encoding)
        
        for file in files:
            if file.filename == '' or not file.filename.endswith('.lzw'):
                continue
            
            # Save uploaded .lzw file
            compressed_path = os.path.join(compressed_folder, file.filename)
            file.save(compressed_path)
            
            # Read compressed data
            with open(compressed_path, 'rb') as f:
                compressed_data = f.read()
            
            # Decompress
            start_time = time.time()
            decompressed_text = compressor.decompress(compressed_data)
            processing_time = time.time() - start_time
            
            # Save decompressed file
            decompressed_filename = f"decompressed_{session_id}_{file.filename[:-4]}"
            decompressed_path = os.path.join(compressed_folder, decompressed_filename)
            with open(decompressed_path, 'w', encoding=encoding) as f_out:
                f_out.write(decompressed_text)
            
            decompressed_size = os.path.getsize(decompressed_path)
            
            # Log decompression (no database entry for decompressed files)
            db_manager.log_action(
                user_id,
                'FILE_DECOMPRESSION',
                'SUCCESS',
                f'Decompressed {file.filename} (encoding: {encoding})',
                request.remote_addr,
                request.user_agent.string
            )
            
            decompressed_files.append(decompressed_path)
        
        # Create zip file for decompressed files
        zip_path = os.path.join(compressed_folder, f"decompressed_{session_id}.zip")
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for decompressed_path in decompressed_files:
                zipf.write(decompressed_path, os.path.basename(decompressed_path))
        
        cursor.close()
        conn.close()
        
        download_url = f"/compressed/decompressed_{session_id}.zip"
        
        return jsonify({
            "message": "Decompression successful",
            "decompressed_files": len(decompressed_files),
            "download_url": download_url
        }), 200
        
    except Exception as e:
        logger.error(f"Decompression error: {e}")
        db_manager.log_action(
            user_id,
            'FILE_DECOMPRESSION',
            'FAILED',
            f'Decompression failed: {str(e)}',
            request.remote_addr,
            request.user_agent.string
        )
        return jsonify({"error": f"Decompression failed: {str(e)}"}), 500

@app.route('/api/cleanup', methods=['POST'])
@jwt_required()
def cleanup():
    """Manually trigger cleanup of old files and database entries"""
    try:
        user_id = get_jwt_identity()
        
        if not db_manager.verify_user(user_id):
            return jsonify({"error": "User not found or inactive"}), 404
        
        conn = db_manager.get_connection()
        if not conn:
            return jsonify({"error": "Database connection failed"}), 500
        
        cursor = conn.cursor()
        cursor.execute("SELECT is_active FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user or not user['is_active']:
            cursor.close()
            conn.close()
            return jsonify({"error": "Unauthorized user"}), 403
        
        days_old = request.form.get('days_old', 30, type=int)
        if days_old < 1:
            return jsonify({"error": "Days must be positive"}), 400
        
        if db_manager.cleanup_old_data(days_old):
            db_manager.log_action(
                user_id,
                'CLEANUP',
                'SUCCESS',
                f'Cleaned up files and logs older than {days_old} days',
                request.remote_addr,
                request.user_agent.string
            )
            return jsonify({"message": f"Cleaned up files and logs older than {days_old} days"}), 200
        else:
            return jsonify({"error": "Cleanup failed"}), 500
            
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        return jsonify({"error": f"Cleanup failed: {str(e)}"}), 500

@app.route('/compressed/<filename>')
@jwt_required()
def download_compressed(filename):
    """Serve compressed or decompressed files"""
    try:
        user_id = get_jwt_identity()
        
        if not db_manager.verify_user(user_id):
            return jsonify({"error": "User not found or inactive"}), 404
        
        compressed_folder = os.getenv("COMPRESSED_FOLDER", "compressed")
        return send_from_directory(compressed_folder, filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({"error": "Failed to download file"}), 404

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    print("🚀 Initializing Multilingual Text Compression application...")
    
    create_upload_directories()
    
    print("📊 Initializing database schema...")
    
    db_schema = """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        registration_date TEXT DEFAULT CURRENT_TIMESTAMP,
        last_login TEXT,
        is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS files (
        file_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        file_name TEXT NOT NULL,
        original_size INTEGER NOT NULL,
        file_encoding TEXT DEFAULT 'utf-8',
        file_type TEXT DEFAULT 'txt',
        upload_time TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
    );

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
    );

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
    );

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
    );

    CREATE TABLE IF NOT EXISTS user_preferences (
        preference_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        preference_name TEXT NOT NULL,
        preference_value TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        UNIQUE (user_id, preference_name)
    );

    CREATE INDEX IF NOT EXISTS idx_username ON users(username);
    CREATE INDEX IF NOT EXISTS idx_email ON users(email);
    CREATE INDEX IF NOT EXISTS idx_registration_date ON users(registration_date);
    CREATE INDEX IF NOT EXISTS idx_user_id ON files(user_id);
    CREATE INDEX IF NOT EXISTS idx_upload_time ON files(upload_time);
    CREATE INDEX IF NOT EXISTS idx_file_name ON files(file_name);
    CREATE INDEX IF NOT EXISTS idx_file_id ON compression_results(file_id);
    CREATE INDEX IF NOT EXISTS idx_session_id ON compression_results(session_id);
    CREATE INDEX IF NOT EXISTS idx_date_processed ON compression_results(date_processed);
    CREATE INDEX IF NOT EXISTS idx_algorithm ON compression_results(algorithm_used);
    CREATE INDEX IF NOT EXISTS idx_user_id ON logs(user_id);
    CREATE INDEX IF NOT EXISTS idx_timestamp ON logs(timestamp);
    CREATE INDEX IF NOT EXISTS idx_action ON logs(action);
    CREATE INDEX IF NOT EXISTS idx_status ON logs(status);
    CREATE INDEX IF NOT EXISTS idx_stat_date ON system_stats(stat_date);
    CREATE INDEX IF NOT EXISTS idx_user_id ON user_preferences(user_id);

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
    GROUP BY u.user_id, u.username, u.email;

    CREATE VIEW IF NOT EXISTS recent_activity AS
    SELECT 
        u.username,
        l.action,
        l.status,
        l.details,
        l.timestamp AS activity_time
    FROM logs l
    LEFT JOIN users u ON l.user_id = u.user_id
    ORDER BY l.timestamp DESC;
    """
    
    if db_manager.execute_script_from_file(db_schema):
        print("✅ Database schema is up to date.")
    else:
        print("❌ Failed to initialize database schema.")
        sys.exit(1)
    app.run(host='0.0.0.0', port=5001, debug=True)