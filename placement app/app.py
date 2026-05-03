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


# ─── Load Model ────────────────────────────────────────────────────────────────
MODEL_PATH = os.path.join(os.path.dirname(__file__), "md.pkl")
model = pickle.load(open(MODEL_PATH, "rb"))

# ─── Encoding Maps ─────────────────────────────────────────────────────────────
GENDER_MAP = {'Male': 1, 'Female': 0}
DEGREE_MAP = {'B.Tech': 1, 'BCA': 2, 'MCA': 3, 'B.Sc': 0}

# ─── MySQL Config ──────────────────────────────────────────────────────────────
DB_CONFIG = {
    'host': 'localhost',
    'port': 3310,
    'user': 'root',
    'password': 'root1234',   # change if needed
    'database': 'placement_db'
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
        # Seed default admin only if table is empty
        cursor.execute("SELECT COUNT(*) FROM admins")
        count = cursor.fetchone()[0]
        if count == 0:
            cursor.execute(
                "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
                (DEFAULT_ADMIN_USER, generate_password_hash(DEFAULT_ADMIN_PASS))
            )
            print(f"[INIT] Default admin created → username: '{DEFAULT_ADMIN_USER}' / password: '{DEFAULT_ADMIN_PASS}'")
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
    """Root: redirect to home if logged in, else to login."""
    if session.get('admin_logged_in'):
        return redirect(url_for('home_stats'))
    return redirect(url_for('admin_login'))


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
                SUM(prediction_result = 'Placed')           AS placed,
                SUM(prediction_result = 'Not Placed')       AS not_placed
            FROM predictions
        """)
        overall = cursor.fetchone()

        # Degree-wise and Class-wise breakdown
        cursor.execute("""
            SELECT degree, student_class,
                   COUNT(DISTINCT student_name)              AS students,
                   COUNT(*)                                  AS total,
                   SUM(prediction_result = 'Placed')         AS placed,
                   SUM(prediction_result = 'Not Placed')     AS not_placed
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

        return render_template('home.html',
                               overall=overall,
                               degree_stats=degree_stats,
                               active_page='home')
    except Error as e:
        return f"<h3 style='color:red'>DB Error: {e}</h3>"
    finally:
        cursor.close()
        conn.close()


@app.route('/prediction')
@login_required
def prediction_form():
    """Prediction form page."""
    return render_template('prediction.html', active_page='prediction')


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
        prob       = model.predict_proba(data)[0][1]
        result     = "Placed" if prediction == 1 else "Not Placed"

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
                prob = model.predict_proba(data)[0][1]
                result = "Placed" if prediction == 1 else "Not Placed"
                
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
            "SELECT COUNT(*) AS cnt FROM predictions WHERE prediction_result = 'Placed' AND degree = %s AND student_class = %s",
            (selected_degree, selected_class)
        )
        placed_count = cursor.fetchone()["cnt"]

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM predictions WHERE prediction_result = 'Not Placed' AND degree = %s AND student_class = %s",
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
                   SUM(prediction_result = 'Placed') AS placed,
                   SUM(prediction_result = 'Not Placed') AS not_placed
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
            active_page='dashboard'
        )


    except Error as e:
        return f"<h3 style='color:red;font-family:sans-serif'>DB Query Error: {e}</h3>"
    finally:
        cursor.close()
        conn.close()


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
            query += " AND prediction_result = 'Placed'"
        elif filter_type == 'not_placed':
            query += " AND prediction_result = 'Not Placed'"

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
            
            # If the student is already Placed and has no major flaws, it says 'You are on track'
            # If the user specifically wants reasons for Not Placed, this will accurately reflect the flaws.
            row['recommendation'] = " | ".join(recs)

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


if __name__ == "__main__":
    app.run(debug=True)