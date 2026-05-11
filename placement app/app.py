from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for, flash
import pickle
import numpy as np
import os
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import csv
import io

from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'placementai-super-secret-2024'   # change in production

# ─── Default Admin (created in DB on first run) ────────────────────────────
DEFAULT_ADMIN_USER = 'admin'
DEFAULT_ADMIN_PASS = 'admin@123'

# ─── Login Required Decorator ───────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated

def student_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('student_logged_in'):
            return redirect(url_for('student_login'))
        return f(*args, **kwargs)
    return decorated


# ─── Load Model ────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.join(os.path.dirname(__file__), "md.pkl")
model = pickle.load(open(MODEL_PATH, "rb"))

# ─── Encoding Maps ─────────────────────────────────────────────────────────────
GENDER_MAP = {'Male': 1, 'Female': 0}
DEGREE_MAP = {'B.Tech': 1, 'BCA': 2, 'MCA': 3, 'B.Sc': 0}

# ─── MySQL Config ──────────────────────────────────────────────────────────────
DB_CONFIG = {
    'host': 'localhost',
    'port': 5500,
    'user': 'root',
    'password': 'root1234',   # change if needed
    'database': 'placement_database'
}

def get_db_connection():
    """Return a new MySQL connection or None on failure."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"[DB ERROR] {e}")
        return None

# ─── DB Init: create admins table + default admin ─────────────────────────────
def init_db():
    """Create admins table if not exists and seed one default admin."""
    conn = get_db_connection()
    if not conn:
        print("[INIT] Warning: could not connect to DB for init.")
        return
    try:
        cursor = conn.cursor()
        # Create table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                id            INT          AUTO_INCREMENT PRIMARY KEY,
                username      VARCHAR(60)  NOT NULL UNIQUE,
                password_hash VARCHAR(256) NOT NULL,
                created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Create students table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                email VARCHAR(120) UNIQUE NOT NULL,
                password_hash VARCHAR(256) NOT NULL,
                degree VARCHAR(20) NOT NULL,
                student_class VARCHAR(30) NOT NULL,
                gender VARCHAR(10) NOT NULL,
                cgpa FLOAT DEFAULT 0,
                internships INT DEFAULT 0,
                projects INT DEFAULT 0,
                backlogs INT DEFAULT 0,
                coding_skills FLOAT DEFAULT NULL,
                communication_skills FLOAT DEFAULT NULL,
                aptitude_test_score FLOAT DEFAULT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Create predictions table if not exists (minimal version for python init)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS predictions (
                id                      INT           AUTO_INCREMENT PRIMARY KEY,
                student_name            VARCHAR(120)  NOT NULL,
                student_class           VARCHAR(30)   NOT NULL,
                cgpa                    FLOAT         NOT NULL,
                internships             FLOAT         NOT NULL,
                projects                FLOAT         NOT NULL,
                coding_skills           FLOAT         NOT NULL,
                communication_skills    FLOAT         NOT NULL,
                aptitude_test_score     FLOAT         NOT NULL,
                backlogs                FLOAT         NOT NULL,
                degree                  VARCHAR(20)   NOT NULL,
                gender                  VARCHAR(10)   NOT NULL,
                avg_score               FLOAT         NOT NULL,
                total_skills            FLOAT         NOT NULL,
                is_weak                 TINYINT(1)    NOT NULL,
                prediction_result       VARCHAR(20)   NOT NULL,
                probability             FLOAT         NOT NULL,
                created_at              DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Seed default admin only if table is empty
        cursor.execute("SELECT COUNT(*) FROM admins")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                (DEFAULT_ADMIN_USER, generate_password_hash(DEFAULT_ADMIN_PASS))
            )
            print(f"[INIT] Default admin created → username: '{DEFAULT_ADMIN_USER}' / password: '{DEFAULT_ADMIN_PASS}'")
        
        # Add a trigger to automatically delete predictions when a student is deleted from the database
        cursor.execute("DROP TRIGGER IF EXISTS after_student_delete")
        cursor.execute("""
            CREATE TRIGGER after_student_delete
            AFTER DELETE ON students
            FOR EACH ROW
            BEGIN
                DELETE FROM predictions 
                WHERE student_name = OLD.name 
                  AND degree = OLD.degree 
                  AND student_class = OLD.student_class;
            END;
        """)
        
        conn.commit()
    except Error as e:
        print(f"[INIT ERROR] {e}")
    finally:
        cursor.close()
        conn.close()

# Run once on startup
with app.app_context():
    init_db()

# ─── Recommendation Engine ─────────────────────────────────────────────────────
def recommend(student):
    recs = []
    if student["CGPA"] < 6:
        recs.append("Improve CGPA")
    if student["Coding_Skills"] < 6:
        recs.append("Practice coding")
    if student["Communication_Skills"] < 6:
        recs.append("Improve communication")
    if student["Aptitude_Test_Score"] < 60:
        recs.append("Practice aptitude")
    if student["Internships"] == 0:
        recs.append("Do internship")
    if student["Projects"] < 2:
        recs.append("Build projects")
    if student["Backlogs"] > 0:
        recs.append("Clear backlogs")
    if not recs:
        recs.append("You are on track")
    return recs

# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Root: redirect to student portal."""
    if session.get('student_logged_in'):
        return redirect(url_for('student_dashboard'))
    if session.get('admin_logged_in'):
        return redirect(url_for('home_stats'))
    return redirect(url_for('student_login'))


@app.route('/home')
@login_required
def home_stats():
    """Home page: overall + class-wise placement stats."""
    conn = get_db_connection()
    if not conn:
        return "<h3 style='color:red;font-family:sans-serif'>Database connection failed.</h3>"
    try:
        cursor = conn.cursor(dictionary=True)

        # Overall totals
        cursor.execute("""
            SELECT
                COUNT(DISTINCT student_name)                AS total_students,
                COUNT(*)                                    AS total_predictions,
                SUM(prediction_result = 'Ready to Place')           AS placed,
                SUM(prediction_result = 'Not Ready to Place')       AS not_placed
            FROM predictions
        """)
        overall = cursor.fetchone()

        # Degree-wise and Class-wise breakdown
        cursor.execute("""
            SELECT degree, student_class,
                   COUNT(DISTINCT student_name)              AS students,
                   COUNT(*)                                  AS total,
                   SUM(prediction_result = 'Ready to Place')         AS placed,
                   SUM(prediction_result = 'Not Ready to Place')     AS not_placed
            FROM predictions
            GROUP BY degree, student_class
            ORDER BY degree, student_class
        """)
        raw_class_stats = cursor.fetchall()

        degrees = ['B.Tech', 'BCA', 'MCA', 'B.Sc']
        degree_stats = {d: {'classes': {}, 'overall': {'students': 0, 'total': 0, 'placed': 0, 'not_placed': 0}} for d in degrees}

        for row in raw_class_stats:
            d = row['degree']
            c = row['student_class']
            if d not in degree_stats:
                degree_stats[d] = {'classes': {}, 'overall': {'students': 0, 'total': 0, 'placed': 0, 'not_placed': 0}}
            
            placed_val = int(row['placed'] or 0)
            not_placed_val = int(row['not_placed'] or 0)
            total_val = int(row['total'] or 0)
            students_val = int(row['students'] or 0)

            degree_stats[d]['classes'][c] = {
                'students': students_val,
                'total': total_val,
                'placed': placed_val,
                'not_placed': not_placed_val
            }
            degree_stats[d]['overall']['students'] += students_val
            degree_stats[d]['overall']['total'] += total_val
            degree_stats[d]['overall']['placed'] += placed_val
            degree_stats[d]['overall']['not_placed'] += not_placed_val

        cursor.execute("""
            SELECT 
                MAX(id) as id,
                student_name as name, 
                degree, 
                student_class, 
                MAX(created_at) as created_at
            FROM predictions 
            GROUP BY student_name, degree, student_class
            ORDER BY created_at DESC
        """)
        all_students = cursor.fetchall()

        return render_template('home.html',
                               overall=overall,
                               degree_stats=degree_stats,
                               all_students=all_students,
                               active_page='home')
    except Error as e:
        return f"<h3 style='color:red'>DB Error: {e}</h3>"
    finally:
        cursor.close()
        conn.close()


@app.route('/prediction')
@login_required
def prediction_form():
    """Prediction form page & Registered Students List."""
    conn = get_db_connection()
    students = []
    if conn:
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM students ORDER BY created_at DESC")
            students = cursor.fetchall()
            
            # For each student, check if prediction exists
            for s in students:
                cursor.execute("SELECT prediction_result FROM predictions WHERE student_name = %s AND student_class = %s AND degree = %s LIMIT 1",
                               (s['name'], s['student_class'], s['degree']))
                pred = cursor.fetchone()
                s['has_prediction'] = True if pred else False
                s['prediction'] = pred['prediction_result'] if pred else None
                s['tests_complete'] = s['coding_skills'] is not None and s['communication_skills'] is not None and s['aptitude_test_score'] is not None
        finally:
            cursor.close()
            conn.close()
            
    return render_template('prediction.html', students=students, active_page='prediction')


@app.route('/predict', methods=['POST'])
def predict():
    try:
        form = request.form

        # ── New fields ──────────────────────────────────────────────────────
        student_name = form.get("student_name", "Unknown").strip()
        student_class = form.get("student_class", "N/A").strip()

        # ── Existing inputs ─────────────────────────────────────────────────
        cgpa        = float(form["CGPA"])
        internships = float(form["Internships"])
        projects    = float(form["Projects"])
        coding      = float(form["Coding_Skills"])
        comm        = float(form["Communication_Skills"])
        aptitude    = float(form["Aptitude_Test_Score"])
        backlogs    = float(form["Backlogs"])
        gender      = GENDER_MAP.get(form["Gender"], 1)
        degree      = DEGREE_MAP.get(form["Degree"], 1)

        # ── Feature engineering (same as training — DO NOT CHANGE) ──────────
        avg_score   = (cgpa + internships + projects) / 3
        total_skills = aptitude + comm + coding
        is_weak     = 1 if cgpa < 6 else 0

        # ── Correct feature order (12 features) ─────────────────────────────
        data = np.array([[
            cgpa, internships, projects,
            coding, comm, aptitude,
            backlogs, degree, gender,
            avg_score, total_skills, is_weak
        ]])

        prediction = model.predict(data)[0]
        prob       = max(model.predict_proba(data)[0])
        result     = "Ready to Place" if prediction == 1 else "Not Ready to Place"

        # ── Recommendations ──────────────────────────────────────────────────
        student_dict = {
            "CGPA": cgpa, "Coding_Skills": coding,
            "Communication_Skills": comm, "Aptitude_Test_Score": aptitude,
            "Internships": internships, "Projects": projects, "Backlogs": backlogs
        }
        recs = recommend(student_dict)

        # ── Upsert to MySQL ──────────────────────────────────────────────────
        is_update = False
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()

                # Check if this student already has a record for this degree+class
                cursor.execute(
                    """SELECT id FROM predictions
                       WHERE student_name = %s AND student_class = %s AND degree = %s
                       LIMIT 1""",
                    (student_name, student_class, form["Degree"])
                )
                existing = cursor.fetchone()

                if existing:
                    # ── UPDATE existing record ──
                    is_update = True
                    cursor.execute(
                        """UPDATE predictions SET
                               cgpa=%s, internships=%s, projects=%s,
                               coding_skills=%s, communication_skills=%s,
                               aptitude_test_score=%s, backlogs=%s, gender=%s,
                               avg_score=%s, total_skills=%s, is_weak=%s,
                               prediction_result=%s, probability=%s,
                               created_at=%s
                           WHERE id=%s""",
                        (
                            cgpa, internships, projects,
                            coding, comm, aptitude, backlogs, form["Gender"],
                            round(avg_score, 4), round(total_skills, 4), is_weak,
                            result, round(prob * 100, 2), datetime.now(),
                            existing[0]
                        )
                    )
                else:
                    # ── INSERT new record ──
                    cursor.execute(
                        """INSERT INTO predictions
                               (student_name, student_class, cgpa, internships, projects,
                                coding_skills, communication_skills, aptitude_test_score,
                                backlogs, degree, gender, avg_score, total_skills, is_weak,
                                prediction_result, probability, created_at)
                           VALUES
                               (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            student_name, student_class, cgpa, internships, projects,
                            coding, comm, aptitude, backlogs,
                            form["Degree"], form["Gender"],
                            round(avg_score, 4), round(total_skills, 4), is_weak,
                            result, round(prob * 100, 2), datetime.now()
                        )
                    )
                # Upsert into students table
                cursor.execute(
                    "SELECT id FROM students WHERE name = %s AND student_class = %s AND degree = %s LIMIT 1",
                    (student_name, student_class, form["Degree"])
                )
                existing_student = cursor.fetchone()
                
                if not existing_student:
                    default_password = generate_password_hash("student123")
                    dummy_email = f"{student_name.lower().replace(' ', '')}.{int(datetime.now().timestamp() * 1000)}@manual.student"
                    
                    cursor.execute(
                        """INSERT INTO students (name, email, password_hash, degree, student_class, gender, cgpa, internships, projects, backlogs, coding_skills, communication_skills, aptitude_test_score)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (student_name, dummy_email, default_password, form["Degree"], student_class, form["Gender"], cgpa, internships, projects, backlogs, coding, comm, aptitude)
                    )
                else:
                    cursor.execute(
                        """UPDATE students SET cgpa=%s, internships=%s, projects=%s, backlogs=%s, coding_skills=%s, communication_skills=%s, aptitude_test_score=%s
                           WHERE id=%s""",
                        (cgpa, internships, projects, backlogs, coding, comm, aptitude, existing_student[0])
                    )

                conn.commit()
            except Error as e:
                print(f"[DB ERROR] {e}")
            finally:
                cursor.close()
                conn.close()

        return render_template(
            "result.html",
            student_name=student_name,
            student_class=student_class,
            prediction=result,
            probability=round(prob * 100, 2),
            recommendations=recs,
            is_update=is_update,
            active_page='prediction'
        )



    except Exception as e:
        return f"<h3 style='color:red;font-family:sans-serif'>Error: {str(e)}</h3>"


@app.route('/predict_bulk', methods=['POST'])
@login_required
def predict_bulk():
    try:
        if 'csv_file' not in request.files:
            flash("No file part", "error")
            return redirect(url_for('prediction_form'))
        
        file = request.files['csv_file']
        if file.filename == '':
            flash("No selected file", "error")
            return redirect(url_for('prediction_form'))
            
        if not file.filename.endswith('.csv'):
            flash("Please upload a CSV file.", "error")
            return redirect(url_for('prediction_form'))

        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.DictReader(stream)
        
        conn = get_db_connection()
        if not conn:
            flash("Database connection failed.", "error")
            return redirect(url_for('prediction_form'))
            
        cursor = conn.cursor()
        
        success_count = 0
        error_count = 0
        
        default_password = generate_password_hash("student123")
        
        for row in csv_input:
            try:
                student_name = row.get("student_name", "Unknown").strip()
                student_class = row.get("student_class", "N/A").strip()
                
                cgpa = float(row.get("CGPA", 0))
                internships = float(row.get("Internships", 0))
                projects = float(row.get("Projects", 0))
                coding = float(row.get("Coding_Skills", 0))
                comm = float(row.get("Communication_Skills", 0))
                aptitude = float(row.get("Aptitude_Test_Score", 0))
                backlogs = float(row.get("Backlogs", 0))
                
                gender_str = row.get("Gender", "Male").strip()
                degree_str = row.get("Degree", "B.Tech").strip()
                
                gender = GENDER_MAP.get(gender_str, 1)
                degree = DEGREE_MAP.get(degree_str, 1)
                
                avg_score = (cgpa + internships + projects) / 3
                total_skills = aptitude + comm + coding
                is_weak = 1 if cgpa < 6 else 0
                
                data = np.array([[
                    cgpa, internships, projects,
                    coding, comm, aptitude,
                    backlogs, degree, gender,
                    avg_score, total_skills, is_weak
                ]])
                
                prediction = model.predict(data)[0]
                prob = max(model.predict_proba(data)[0])
                result = "Ready to Place" if prediction == 1 else "Not Ready to Place"
                
                cursor.execute(
                    """SELECT id FROM predictions
                       WHERE student_name = %s AND student_class = %s AND degree = %s
                       LIMIT 1""",
                    (student_name, student_class, degree_str)
                )
                existing = cursor.fetchone()
                
                if existing:
                    cursor.execute(
                        """UPDATE predictions SET
                               cgpa=%s, internships=%s, projects=%s,
                               coding_skills=%s, communication_skills=%s,
                               aptitude_test_score=%s, backlogs=%s, gender=%s,
                               avg_score=%s, total_skills=%s, is_weak=%s,
                               prediction_result=%s, probability=%s,
                               created_at=%s
                           WHERE id=%s""",
                        (
                            cgpa, internships, projects,
                            coding, comm, aptitude, backlogs, gender_str,
                            round(avg_score, 4), round(total_skills, 4), is_weak,
                            result, round(prob * 100, 2), datetime.now(),
                            existing[0]
                        )
                    )
                else:
                    cursor.execute(
                        """INSERT INTO predictions
                               (student_name, student_class, cgpa, internships, projects,
                                coding_skills, communication_skills, aptitude_test_score,
                                backlogs, degree, gender, avg_score, total_skills, is_weak,
                                prediction_result, probability, created_at)
                           VALUES
                               (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            student_name, student_class, cgpa, internships, projects,
                            coding, comm, aptitude, backlogs,
                            degree_str, gender_str,
                            round(avg_score, 4), round(total_skills, 4), is_weak,
                            result, round(prob * 100, 2), datetime.now()
                        )
                    )
                
                # Upsert into students table
                cursor.execute(
                    "SELECT id FROM students WHERE name = %s AND student_class = %s AND degree = %s LIMIT 1",
                    (student_name, student_class, degree_str)
                )
                existing_student = cursor.fetchone()
                
                if not existing_student:
                    # Generate a unique dummy email
                    dummy_email = f"{student_name.lower().replace(' ', '')}.{int(datetime.now().timestamp() * 1000)}@bulk.student"
                    
                    cursor.execute(
                        """INSERT INTO students (name, email, password_hash, degree, student_class, gender, cgpa, internships, projects, backlogs, coding_skills, communication_skills, aptitude_test_score)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (student_name, dummy_email, default_password, degree_str, student_class, gender_str, cgpa, internships, projects, backlogs, coding, comm, aptitude)
                    )
                else:
                    cursor.execute(
                        """UPDATE students SET cgpa=%s, internships=%s, projects=%s, backlogs=%s, coding_skills=%s, communication_skills=%s, aptitude_test_score=%s
                           WHERE id=%s""",
                        (cgpa, internships, projects, backlogs, coding, comm, aptitude, existing_student[0])
                    )
                
                success_count += 1
            except Exception as row_e:
                print(f"[CSV ROW ERROR] {row_e}")
                error_count += 1
                
        conn.commit()
        cursor.close()
        conn.close()
        
        flash(f"Successfully processed {success_count} students. Errors: {error_count}.", "success" if error_count == 0 else "warning")
        return redirect(url_for('prediction_form'))
        
    except Exception as e:
        flash(f"Error processing CSV: {str(e)}", "error")
        return redirect(url_for('prediction_form'))

@app.route('/admin/predict_student/<int:student_id>', methods=['POST'])
@login_required
def admin_predict_student(student_id):
    conn = get_db_connection()
    if not conn:
        flash("Database error", "error")
        return redirect(url_for('prediction_form'))
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM students WHERE id = %s", (student_id,))
        student = cursor.fetchone()
        
        if not student:
            flash("Student not found", "error")
            return redirect(url_for('prediction_form'))
            
        # Check if tests are taken
        if student['coding_skills'] is None or student['communication_skills'] is None or student['aptitude_test_score'] is None:
            flash(f"Student {student['name']} has not completed all tests yet.", "error")
            return redirect(url_for('prediction_form'))
            
        cgpa = float(student['cgpa'])
        internships = float(student['internships'])
        projects = float(student['projects'])
        coding = float(student['coding_skills'])
        comm = float(student['communication_skills'])
        aptitude = float(student['aptitude_test_score'])
        backlogs = float(student['backlogs'])
        gender = GENDER_MAP.get(student['gender'], 1)
        degree = DEGREE_MAP.get(student['degree'], 1)
        
        avg_score = (cgpa + internships + projects) / 3
        total_skills = aptitude + comm + coding
        is_weak = 1 if cgpa < 6 else 0
        
        data = np.array([[
            cgpa, internships, projects,
            coding, comm, aptitude,
            backlogs, degree, gender,
            avg_score, total_skills, is_weak
        ]])
        
        prediction_val = model.predict(data)[0]
        prob = max(model.predict_proba(data)[0])
        result = "Ready to Place" if prediction_val == 1 else "Not Ready to Place"
        
        # Upsert to predictions
        cursor.execute(
            "SELECT id FROM predictions WHERE student_name = %s AND student_class = %s AND degree = %s LIMIT 1",
            (student['name'], student['student_class'], student['degree'])
        )
        existing = cursor.fetchone()
        
        if existing:
            cursor.execute(
                """UPDATE predictions SET
                       cgpa=%s, internships=%s, projects=%s,
                       coding_skills=%s, communication_skills=%s,
                       aptitude_test_score=%s, backlogs=%s, gender=%s,
                       avg_score=%s, total_skills=%s, is_weak=%s,
                       prediction_result=%s, probability=%s,
                       created_at=%s
                   WHERE id=%s""",
                (
                    cgpa, internships, projects,
                    coding, comm, aptitude, backlogs, student['gender'],
                    round(avg_score, 4), round(total_skills, 4), is_weak,
                    result, round(prob * 100, 2), datetime.now(),
                    existing['id']
                )
            )
        else:
            cursor.execute(
                """INSERT INTO predictions
                       (student_name, student_class, cgpa, internships, projects,
                        coding_skills, communication_skills, aptitude_test_score,
                        backlogs, degree, gender, avg_score, total_skills, is_weak,
                        prediction_result, probability, created_at)
                   VALUES
                       (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    student['name'], student['student_class'], cgpa, internships, projects,
                    coding, comm, aptitude, backlogs,
                    student['degree'], student['gender'],
                    round(avg_score, 4), round(total_skills, 4), is_weak,
                    result, round(prob * 100, 2), datetime.now()
                )
            )
            
        conn.commit()
        flash(f"Prediction for {student['name']} completed: {result}", "success")
    except Exception as e:
        print(f"[PREDICTION ERROR] {e}")
        flash(f"Error predicting for student: {e}", "error")
    finally:
        cursor.close()
        conn.close()
        
    return redirect(url_for('prediction_form'))


@app.route('/admin/predict_registered_bulk', methods=['POST'])
@login_required
def predict_registered_bulk():
    degree = request.form.get('degree')
    student_class = request.form.get('student_class')
    
    if not degree or not student_class:
        flash("Degree and Class are required for bulk prediction.", "error")
        return redirect(url_for('prediction_form'))
        
    conn = get_db_connection()
    if not conn:
        flash("Database error", "error")
        return redirect(url_for('prediction_form'))
        
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM students WHERE degree = %s AND student_class = %s", (degree, student_class))
        students = cursor.fetchall()
        
        if not students:
            flash(f"No registered students found for {degree} - {student_class}.", "warning")
            return redirect(url_for('prediction_form'))
            
        success_count = 0
        skip_count = 0
        error_count = 0
        
        for student in students:
            # Check if tests are taken
            if student['coding_skills'] is None or student['communication_skills'] is None or student['aptitude_test_score'] is None:
                skip_count += 1
                continue
                
            try:
                cgpa = float(student['cgpa'])
                internships = float(student['internships'])
                projects = float(student['projects'])
                coding = float(student['coding_skills'])
                comm = float(student['communication_skills'])
                aptitude = float(student['aptitude_test_score'])
                backlogs = float(student['backlogs'])
                gender = GENDER_MAP.get(student['gender'], 1)
                deg = DEGREE_MAP.get(student['degree'], 1)
                
                avg_score = (cgpa + internships + projects) / 3
                total_skills = aptitude + comm + coding
                is_weak = 1 if cgpa < 6 else 0
                
                data = np.array([[
                    cgpa, internships, projects,
                    coding, comm, aptitude,
                    backlogs, deg, gender,
                    avg_score, total_skills, is_weak
                ]])
                
                prediction_val = model.predict(data)[0]
                prob = max(model.predict_proba(data)[0])
                result = "Ready to Place" if prediction_val == 1 else "Not Ready to Place"
                
                # Upsert to predictions
                cursor.execute(
                    "SELECT id FROM predictions WHERE student_name = %s AND student_class = %s AND degree = %s LIMIT 1",
                    (student['name'], student['student_class'], student['degree'])
                )
                existing = cursor.fetchone()
                
                if existing:
                    cursor.execute(
                        """UPDATE predictions SET
                               cgpa=%s, internships=%s, projects=%s,
                               coding_skills=%s, communication_skills=%s,
                               aptitude_test_score=%s, backlogs=%s, gender=%s,
                               avg_score=%s, total_skills=%s, is_weak=%s,
                               prediction_result=%s, probability=%s,
                               created_at=%s
                           WHERE id=%s""",
                        (
                            cgpa, internships, projects,
                            coding, comm, aptitude, backlogs, student['gender'],
                            round(avg_score, 4), round(total_skills, 4), is_weak,
                            result, round(prob * 100, 2), datetime.now(),
                            existing['id']
                        )
                    )
                else:
                    cursor.execute(
                        """INSERT INTO predictions
                               (student_name, student_class, cgpa, internships, projects,
                                coding_skills, communication_skills, aptitude_test_score,
                                backlogs, degree, gender, avg_score, total_skills, is_weak,
                                prediction_result, probability, created_at)
                           VALUES
                               (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (
                            student['name'], student['student_class'], cgpa, internships, projects,
                            coding, comm, aptitude, backlogs,
                            student['degree'], student['gender'],
                            round(avg_score, 4), round(total_skills, 4), is_weak,
                            result, round(prob * 100, 2), datetime.now()
                        )
                    )
                success_count += 1
            except Exception as e:
                print(f"[BULK PREDICT ERROR] Student {student['name']}: {e}")
                error_count += 1
                
        conn.commit()
        
        msg = f"Bulk Prediction Complete for {degree} - {student_class}: {success_count} predicted."
        if skip_count > 0:
            msg += f" Skipped {skip_count} (tests not completed)."
        if error_count > 0:
            msg += f" {error_count} errors occurred."
            
        flash(msg, "success" if success_count > 0 else "warning")
        
    except Exception as e:
        print(f"[PREDICTION ERROR] {e}")
        flash(f"Error predicting for students: {e}", "error")
    finally:
        cursor.close()
        conn.close()
        
    return redirect(url_for('prediction_form'))


@app.route('/download_template')
@login_required
def download_template():
    """Download template CSV for bulk prediction."""
    csv_content = "student_name,student_class,CGPA,Internships,Projects,Coding_Skills,Communication_Skills,Aptitude_Test_Score,Backlogs,Gender,Degree\nJohn Doe,FY,8.5,1,2,7,8,80,0,Male,B.Tech\nJane Smith,SY,9.0,2,3,9,9,90,0,Female,MCA"
    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=prediction_template.csv"}
    )



@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """Admin login page."""
    if session.get('admin_logged_in'):
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute(
                    "SELECT * FROM admins WHERE username = %s LIMIT 1",
                    (username,)
                )
                admin = cursor.fetchone()
            finally:
                cursor.close()
                conn.close()
        else:
            admin = None

        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_logged_in'] = True
            session['admin_user'] = admin['username']
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid username or password.'

    return render_template('login.html', error=error)


@app.route('/admin/logout')
def admin_logout():
    """Clear admin session and redirect to login."""
    session.clear()
    return redirect(url_for('admin_login'))


@app.route('/admin/create', methods=['GET', 'POST'])
@login_required
def admin_create():
    """Create a new admin account (only accessible by logged-in admins)."""
    error = None
    success = None

    if request.method == 'POST':
        new_username = request.form.get('username', '').strip()
        new_password = request.form.get('password', '').strip()
        confirm_pw   = request.form.get('confirm_password', '').strip()

        if not new_username or not new_password:
            error = 'Username and password are required.'
        elif len(new_password) < 6:
            error = 'Password must be at least 6 characters.'
        elif new_password != confirm_pw:
            error = 'Passwords do not match.'
        else:
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                        (new_username, generate_password_hash(new_password))
                    )
                    conn.commit()
                    success = f"Admin '{new_username}' created successfully!"
                except Error as e:
                    if 'Duplicate entry' in str(e):
                        error = f"Username '{new_username}' already exists."
                    else:
                        error = f"Database error: {e}"
                finally:
                    cursor.close()
                    conn.close()
            else:
                error = 'Database connection failed.'

    return render_template('admin_create.html', error=error, success=success, active_page='create_admin')




@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db_connection()
    if not conn:
        return "<h3 style='color:red;font-family:sans-serif'>Database connection failed. Is MySQL running?</h3>"

    selected_degree = request.args.get('degree', '').strip()
    selected_class  = request.args.get('class', '').strip()

    try:
        cursor = conn.cursor(dictionary=True)

        # All degrees available in predictions
        cursor.execute("SELECT DISTINCT degree FROM predictions ORDER BY degree")
        all_degrees = [row['degree'] for row in cursor.fetchall()]

        # Classes filtered by selected degree (for cascading dropdown)
        if selected_degree:
            cursor.execute(
                "SELECT DISTINCT student_class FROM predictions WHERE degree = %s ORDER BY student_class",
                (selected_degree,)
            )
        else:
            cursor.execute("SELECT DISTINCT student_class FROM predictions ORDER BY student_class")
        all_classes = [row['student_class'] for row in cursor.fetchall()]

        # If neither degree nor class is selected → blank state
        if not selected_degree or not selected_class:
            return render_template(
                "dashboard.html",
                selected_degree=selected_degree,
                selected_class='',
                all_degrees=all_degrees,
                all_classes=all_classes,
                total_students=0,
                total_predictions=0,
                placed_count=0,
                not_placed_count=0,
                class_data=[],
                recent=[]
            )

        # ── All queries filtered by degree + class ──────────────────
        cursor.execute(
            "SELECT COUNT(*) AS total FROM predictions WHERE degree = %s AND student_class = %s",
            (selected_degree, selected_class)
        )
        total_predictions = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM predictions WHERE prediction_result = 'Ready to Place' AND degree = %s AND student_class = %s",
            (selected_degree, selected_class)
        )
        placed_count = cursor.fetchone()["cnt"]

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM predictions WHERE prediction_result = 'Not Ready to Place' AND degree = %s AND student_class = %s",
            (selected_degree, selected_class)
        )
        not_placed_count = cursor.fetchone()["cnt"]

        cursor.execute(
            "SELECT COUNT(DISTINCT student_name) AS cnt FROM predictions WHERE degree = %s AND student_class = %s",
            (selected_degree, selected_class)
        )
        total_students = cursor.fetchone()["cnt"]

        # Summary breakdown for the selected degree+class
        cursor.execute("""
            SELECT student_class, degree,
                   COUNT(*) AS total,
                   SUM(prediction_result = 'Ready to Place') AS placed,
                   SUM(prediction_result = 'Not Ready to Place') AS not_placed
            FROM predictions
            WHERE degree = %s AND student_class = %s
            GROUP BY student_class, degree
        """, (selected_degree, selected_class))
        class_data = cursor.fetchall()

        # Recent 10 records
        cursor.execute("""
            SELECT id, student_name, student_class, degree, cgpa, prediction_result,
                   probability, created_at
            FROM predictions
            WHERE degree = %s AND student_class = %s
            ORDER BY created_at DESC
            LIMIT 10
        """, (selected_degree, selected_class))
        recent = cursor.fetchall()

        # All unique students for modal
        cursor.execute("""
            SELECT id, name, email, student_class, degree, created_at
            FROM students
            WHERE degree = %s AND student_class = %s
            ORDER BY name ASC
        """, (selected_degree, selected_class))
        unique_students_list = cursor.fetchall()

        return render_template(
            "dashboard.html",
            selected_degree=selected_degree,
            selected_class=selected_class,
            all_degrees=all_degrees,
            all_classes=all_classes,
            total_students=total_students,
            total_predictions=total_predictions,
            placed_count=placed_count,
            not_placed_count=not_placed_count,
            class_data=class_data,
            recent=recent,
            unique_students_list=unique_students_list,
            active_page='dashboard'
        )

    except Error as e:
        return f"<h3 style='color:red;font-family:sans-serif'>DB Query Error: {e}</h3>"
    finally:
        cursor.close()
        conn.close()


@app.route('/admin/delete_student', methods=['POST'])
@login_required
def admin_delete_student():
    student_name = request.form.get('student_name')
    degree = request.form.get('degree')
    student_class = request.form.get('student_class')
    
    conn = get_db_connection()
    if not conn:
        flash("Database error", "error")
        return redirect(request.referrer or url_for('home_stats'))
        
    try:
        cursor = conn.cursor()
        # Delete from predictions using the student details
        cursor.execute("DELETE FROM predictions WHERE student_name = %s AND degree = %s AND student_class = %s", (student_name, degree, student_class))
        # Delete from students
        cursor.execute("DELETE FROM students WHERE name = %s AND degree = %s AND student_class = %s", (student_name, degree, student_class))
        conn.commit()
        flash(f"Student '{student_name}' and all associated records were permanently deleted.", "success")
            
    except Error as e:
        print(f"[DELETE ERROR] {e}")
        flash(f"Error deleting student: {e}", "error")
    finally:
        cursor.close()
        conn.close()
        
    return redirect(request.referrer or url_for('dashboard'))


@app.route('/dashboard/export')
@login_required
def dashboard_export():
    """Stream all student records for a degree+class as a downloadable CSV."""
    degree         = request.args.get('degree', '').strip()
    student_class  = request.args.get('class', '').strip()
    filter_type    = request.args.get('filter', 'all').strip()

    if not degree or not student_class:
        return Response("Missing degree or class parameter.", status=400)

    conn = get_db_connection()
    if not conn:
        return Response("Database connection failed.", status=500)

    try:
        cursor = conn.cursor(dictionary=True)
        
        query = """
            SELECT id, student_name, student_class, degree, gender,
                   cgpa, internships, projects, coding_skills,
                   communication_skills, aptitude_test_score, backlogs,
                   prediction_result, probability, created_at
            FROM predictions
            WHERE degree = %s AND student_class = %s
        """
        params = [degree, student_class]

        if filter_type == 'placed':
            query += " AND prediction_result = 'Ready to Place'"
        elif filter_type == 'not_placed':
            query += " AND prediction_result = 'Not Ready to Place'"

        query += " ORDER BY created_at DESC"
        
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()

        # Build CSV in-memory
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            'id', 'student_name', 'student_class', 'degree', 'gender',
            'cgpa', 'internships', 'projects', 'coding_skills',
            'communication_skills', 'aptitude_test_score', 'backlogs',
            'prediction_result', 'probability', 'recommendation', 'created_at'
        ])
        writer.writeheader()
        for row in rows:
            # Convert datetime to readable string
            if isinstance(row.get('created_at'), datetime):
                row['created_at'] = row['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            
            # Generate recommendation dynamically
            student_dict = {
                "CGPA": float(row.get("cgpa", 0)),
                "Coding_Skills": float(row.get("coding_skills", 0)),
                "Communication_Skills": float(row.get("communication_skills", 0)),
                "Aptitude_Test_Score": float(row.get("aptitude_test_score", 0)),
                "Internships": float(row.get("internships", 0)),
                "Projects": float(row.get("projects", 0)),
                "Backlogs": float(row.get("backlogs", 0))
            }
            recs = recommend(student_dict)
            
            # If the student is already Ready to Place and has no major flaws, it says 'You are on track'
            # If the user specifically wants reasons for Not Ready to Place, this will accurately reflect the flaws.
            row['recommendation'] = " | ".join(recs)

            if row.get('probability') is not None:
                row['probability'] = f"{row['probability']}%"

            writer.writerow(row)

        csv_data = output.getvalue()
        output.close()

        suffix = f"_{filter_type}" if filter_type != 'all' else ""
        filename = f"{degree}_{student_class}{suffix}_predictions.csv".replace(' ', '_')
        return Response(
            csv_data,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'}
        )

    except Error as e:
        return Response(f"DB Error: {e}", status=500)
    finally:
        cursor.close()
        conn.close()


@app.route('/dashboard/classes')
@login_required
def dashboard_classes():
    """Return JSON list of classes for a given degree (for cascading dropdown)."""
    degree = request.args.get('degree', '').strip()
    if not degree:
        return jsonify({'classes': []})
    conn = get_db_connection()
    if not conn:
        return jsonify({'classes': []})
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT student_class FROM predictions WHERE degree = %s ORDER BY student_class",
            (degree,)
        )
        classes = [row[0] for row in cursor.fetchall()]
        return jsonify({'classes': classes})
    except Error as e:
        return jsonify({'classes': [], 'error': str(e)})
    finally:
        cursor.close()
        conn.close()


# ─── Student Portal Routes ──────────────────────────────────────────────────

@app.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if session.get('student_logged_in'):
        return redirect(url_for('student_dashboard'))
    error = None
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '').strip()
        degree = request.form.get('degree', '').strip()
        student_class = request.form.get('student_class', '').strip()
        gender = request.form.get('gender', '').strip()
        cgpa = request.form.get('cgpa', 0)
        internships = request.form.get('internships', 0)
        projects = request.form.get('projects', 0)
        backlogs = request.form.get('backlogs', 0)

        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO students (name, email, password_hash, degree, student_class, gender, cgpa, internships, projects, backlogs) 
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (name, email, generate_password_hash(password), degree, student_class, gender, cgpa, internships, projects, backlogs)
                )
                conn.commit()
                flash("Registration successful. Please log in.", "success")
                return redirect(url_for('student_login'))
            except Error as e:
                if 'Duplicate entry' in str(e):
                    error = 'Email already registered.'
                else:
                    error = f'Database error: {e}'
            finally:
                cursor.close()
                conn.close()
        else:
            error = 'Database connection failed.'
    return render_template('student_register.html', error=error)


@app.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if session.get('student_logged_in'):
        return redirect(url_for('student_dashboard'))
    error = None
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT * FROM students WHERE email = %s", (email,))
                student = cursor.fetchone()
            finally:
                cursor.close()
                conn.close()
            
            if student and check_password_hash(student['password_hash'], password):
                session['student_logged_in'] = True
                session['student_id'] = student['id']
                session['student_name'] = student['name']
                return redirect(url_for('student_dashboard'))
            else:
                error = 'Invalid email or password.'
        else:
            error = 'Database connection failed.'
    return render_template('student_login.html', error=error)

@app.route('/student/logout')
def student_logout():
    session.pop('student_logged_in', None)
    session.pop('student_id', None)
    session.pop('student_name', None)
    return redirect(url_for('index'))

@app.route('/student/dashboard')
@student_login_required
def student_dashboard():
    conn = get_db_connection()
    if not conn:
        return "Database error"
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM students WHERE id = %s", (session['student_id'],))
        student = cursor.fetchone()
        
        cursor.execute("SELECT * FROM predictions WHERE student_name = %s AND student_class = %s AND degree = %s ORDER BY created_at DESC LIMIT 1",
                       (student['name'], student['student_class'], student['degree']))
        prediction = cursor.fetchone()
        
        # Determine if tests are taken
        tests_taken = {
            'coding': student['coding_skills'] is not None,
            'communication': student['communication_skills'] is not None,
            'aptitude': student['aptitude_test_score'] is not None
        }
    finally:
        cursor.close()
        conn.close()
    return render_template('student_dashboard.html', student=student, prediction=prediction, tests_taken=tests_taken)

@app.route('/student/test/<test_type>', methods=['GET', 'POST'])
@student_login_required
def student_test(test_type):
    if test_type not in ['coding', 'communication', 'aptitude']:
        return redirect(url_for('student_dashboard'))
        
    if request.method == 'POST':
        # Simple score calculation based on form
        score = 0
        if test_type == 'coding':
            score = int(request.form.get('q1', 0)) + int(request.form.get('q2', 0)) + int(request.form.get('q3', 0)) + int(request.form.get('q4', 0)) + int(request.form.get('q5', 0))
            score = min(max(score, 0), 10)
            col = 'coding_skills'
        elif test_type == 'communication':
            score = int(request.form.get('q1', 0)) + int(request.form.get('q2', 0)) + int(request.form.get('q3', 0)) + int(request.form.get('q4', 0)) + int(request.form.get('q5', 0))
            score = min(max(score, 0), 10)
            col = 'communication_skills'
        elif test_type == 'aptitude':
            score = (int(request.form.get('q1', 0)) + int(request.form.get('q2', 0)) + int(request.form.get('q3', 0)) + int(request.form.get('q4', 0)) + int(request.form.get('q5', 0))) * 10
            score = min(max(score, 0), 100)
            col = 'aptitude_test_score'
            
        conn = get_db_connection()
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute(f"UPDATE students SET {col} = %s WHERE id = %s", (score, session['student_id']))
                conn.commit()
                flash(f"{test_type.capitalize()} test submitted successfully! Score: {score}", "success")
            finally:
                cursor.close()
                conn.close()
        return redirect(url_for('student_dashboard'))
        
    return render_template('student_test.html', test_type=test_type)

if __name__ == "__main__":
    app.run(debug=True)