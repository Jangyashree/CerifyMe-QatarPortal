from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import secrets
import os
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = 'qatar-foundation-secret-key-2024'

DB_PATH = os.path.join(os.path.dirname(__file__), 'admin_portal.db')


# ─── DATABASE SETUP ───

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name     TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    DEFAULT (datetime('now'))
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS reset_tokens (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id   INTEGER NOT NULL,
            token      TEXT    UNIQUE NOT NULL,
            expires_at TEXT    NOT NULL,
            used       INTEGER DEFAULT 0,
            FOREIGN KEY (admin_id) REFERENCES admins(id)
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS opportunities (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id             INTEGER NOT NULL,
            name                 TEXT NOT NULL,
            duration             TEXT NOT NULL,
            start_date           TEXT NOT NULL,
            description          TEXT NOT NULL,
            skills               TEXT NOT NULL,
            category             TEXT NOT NULL,
            future_opportunities TEXT NOT NULL,
            max_applicants       INTEGER,
            created_at           TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (admin_id) REFERENCES admins(id)
        )
    ''')
    conn.commit()
    conn.close()


# ─── AUTH DECORATOR ───

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'admin_id' not in session:
            return jsonify({'success': False, 'message': 'Please log in first'}), 401
        return f(*args, **kwargs)
    return decorated


# ─── SERVE FRONTEND FILES ───

@app.route('/')
def index():
    return send_from_directory('sky', 'admin.html')

@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('sky', filename)


# ─── SIGNUP ───

@app.route('/api/signup', methods=['POST'])
def signup():
    data     = request.get_json() or {}
    name     = data.get('name', '').strip()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not name or not email or not password:
        return jsonify({'success': False, 'message': 'All fields are required'}), 400

    if len(password) < 8:
        return jsonify({'success': False, 'message': 'Password must be at least 8 characters'}), 400

    conn = get_db()
    try:
        exists = conn.execute('SELECT id FROM admins WHERE email = ?', (email,)).fetchone()
        if exists:
            return jsonify({'success': False, 'message': 'An account with this email already exists'}), 409

        conn.execute(
            'INSERT INTO admins (full_name, email, password_hash) VALUES (?, ?, ?)',
            (name, email, generate_password_hash(password))
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({'success': True, 'message': 'Account created successfully'}), 201


# ─── LOGIN ───

@app.route('/api/login', methods=['POST'])
def login():
    data        = request.get_json() or {}
    email       = data.get('email', '').strip().lower()
    password    = data.get('password', '')
    remember_me = data.get('rememberMe', False)

    conn = get_db()
    try:
        admin = conn.execute('SELECT * FROM admins WHERE email = ?', (email,)).fetchone()
    finally:
        conn.close()

    if not admin or not check_password_hash(admin['password_hash'], password):
        return jsonify({'success': False, 'message': 'Invalid email or password'}), 401

    session['admin_id']   = admin['id']
    session['admin_name'] = admin['full_name']

    if remember_me:
        session.permanent = True
        app.permanent_session_lifetime = timedelta(days=30)

    return jsonify({
        'success': True,
        'message': 'Login successful',
        'user': {
            'id':    admin['id'],
            'name':  admin['full_name'],
            'email': admin['email']
        }
    })


# ─── LOGOUT ───

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out'})


# ─── FORGOT PASSWORD ───

@app.route('/api/forgot-password', methods=['POST'])
def forgot_password():
    data  = request.get_json() or {}
    email = data.get('email', '').strip().lower()

    conn = get_db()
    try:
        admin = conn.execute('SELECT id FROM admins WHERE email = ?', (email,)).fetchone()
        if admin:
            token      = secrets.token_urlsafe(32)
            expires_at = (datetime.now() + timedelta(hours=1)).isoformat()
            conn.execute(
                'INSERT INTO reset_tokens (admin_id, token, expires_at) VALUES (?, ?, ?)',
                (admin['id'], token, expires_at)
            )
            conn.commit()
            print(f'\n[PASSWORD RESET LINK for {email}]\nhttp://localhost:5000/reset-password/{token}\n')
    finally:
        conn.close()

    # Always same response — protects user privacy
    return jsonify({'success': True, 'message': 'If this email is registered, a reset link has been sent.'})


@app.route('/reset-password/<token>')
def reset_password_page(token):
    conn = get_db()
    try:
        record = conn.execute(
            'SELECT * FROM reset_tokens WHERE token = ? AND used = 0', (token,)
        ).fetchone()
    finally:
        conn.close()

    if not record:
        return '<h2>Invalid or already used reset link.</h2>', 400

    if datetime.now() > datetime.fromisoformat(record['expires_at']):
        return '<h2>This reset link has expired. Please request a new one.</h2>', 400

    return '<h2>Reset link is valid.</h2><p>(Password reset form can be added here.)</p>'


# ─── OPPORTUNITIES ───

def row_to_dict(row):
    d = dict(row)
    d['skills'] = d['skills'].split(',') if d['skills'] else []
    return d


@app.route('/api/opportunities', methods=['GET'])
@login_required
def get_opportunities():
    conn = get_db()
    try:
        rows = conn.execute(
            'SELECT * FROM opportunities WHERE admin_id = ? ORDER BY created_at DESC',
            (session['admin_id'],)
        ).fetchall()
    finally:
        conn.close()

    return jsonify({'success': True, 'opportunities': [row_to_dict(r) for r in rows]})


@app.route('/api/opportunities', methods=['POST'])
@login_required
def create_opportunity():
    data = request.get_json() or {}

    name                 = data.get('name', '').strip()
    duration             = data.get('duration', '').strip()
    start_date           = data.get('startDate', '').strip()
    description          = data.get('description', '').strip()
    skills               = data.get('skills', [])
    category             = data.get('category', '').strip()
    future_opportunities = data.get('futureOpportunities', '').strip()
    max_applicants       = data.get('maxApplicants') or None

    if not all([name, duration, start_date, description, category, future_opportunities]):
        return jsonify({'success': False, 'message': 'All required fields must be filled'}), 400

    if not skills:
        return jsonify({'success': False, 'message': 'At least one skill is required'}), 400

    skills_str = ','.join(skills) if isinstance(skills, list) else skills

    conn = get_db()
    try:
        cursor = conn.execute(
            '''INSERT INTO opportunities
               (admin_id, name, duration, start_date, description,
                skills, category, future_opportunities, max_applicants)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (session['admin_id'], name, duration, start_date, description,
             skills_str, category, future_opportunities, max_applicants)
        )
        opp_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'message': 'Opportunity created successfully',
        'opportunity': {
            'id': opp_id, 'name': name, 'duration': duration,
            'start_date': start_date, 'description': description,
            'skills': skills if isinstance(skills, list) else skills.split(','),
            'category': category,
            'future_opportunities': future_opportunities,
            'max_applicants': max_applicants
        }
    }), 201


@app.route('/api/opportunities/<int:opp_id>', methods=['GET'])
@login_required
def get_opportunity(opp_id):
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT * FROM opportunities WHERE id = ? AND admin_id = ?',
            (opp_id, session['admin_id'])
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return jsonify({'success': False, 'message': 'Opportunity not found'}), 404

    return jsonify({'success': True, 'opportunity': row_to_dict(row)})


@app.route('/api/opportunities/<int:opp_id>', methods=['PUT'])
@login_required
def update_opportunity(opp_id):
    data = request.get_json() or {}

    name                 = data.get('name', '').strip()
    duration             = data.get('duration', '').strip()
    start_date           = data.get('startDate', '').strip()
    description          = data.get('description', '').strip()
    skills               = data.get('skills', [])
    category             = data.get('category', '').strip()
    future_opportunities = data.get('futureOpportunities', '').strip()
    max_applicants       = data.get('maxApplicants') or None

    if not all([name, duration, start_date, description, category, future_opportunities]):
        return jsonify({'success': False, 'message': 'All required fields must be filled'}), 400

    skills_str = ','.join(skills) if isinstance(skills, list) else skills

    conn = get_db()
    try:
        result = conn.execute(
            '''UPDATE opportunities
               SET name=?, duration=?, start_date=?, description=?,
                   skills=?, category=?, future_opportunities=?, max_applicants=?
               WHERE id=? AND admin_id=?''',
            (name, duration, start_date, description, skills_str,
             category, future_opportunities, max_applicants,
             opp_id, session['admin_id'])
        )
        conn.commit()
        if result.rowcount == 0:
            return jsonify({'success': False, 'message': 'Not found or not authorised'}), 404
    finally:
        conn.close()

    return jsonify({
        'success': True,
        'message': 'Opportunity updated successfully',
        'opportunity': {
            'id': opp_id, 'name': name, 'duration': duration,
            'start_date': start_date, 'description': description,
            'skills': skills if isinstance(skills, list) else skills.split(','),
            'category': category,
            'future_opportunities': future_opportunities,
            'max_applicants': max_applicants
        }
    })


@app.route('/api/opportunities/<int:opp_id>', methods=['DELETE'])
@login_required
def delete_opportunity(opp_id):
    conn = get_db()
    try:
        result = conn.execute(
            'DELETE FROM opportunities WHERE id = ? AND admin_id = ?',
            (opp_id, session['admin_id'])
        )
        conn.commit()
        if result.rowcount == 0:
            return jsonify({'success': False, 'message': 'Not found or not authorised'}), 404
    finally:
        conn.close()

    return jsonify({'success': True, 'message': 'Opportunity deleted successfully'})


# ─── START ───

if __name__ == '__main__':
    init_db()
    print('Database connected.')
    print('Server is running on  http://localhost:5000')
    app.run(debug=True)
