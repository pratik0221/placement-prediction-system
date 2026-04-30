from flask import Flask, render_template, request, jsonify, Response
import pickle
import numpy as np
import os
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import csv
import io

app = Flask(__name__)

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

# ─── Recommendation Engine (unchanged) ────────────────────────────────────────
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
def home():
    return render_template("index.html")


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
            is_update=is_update
        )


    except Exception as e:
        return f"<h3 style='color:red;font-family:sans-serif'>Error: {str(e)}</h3>"


@app.route('/dashboard')
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
            recent=recent
        )

    except Error as e:
        return f"<h3 style='color:red;font-family:sans-serif'>DB Query Error: {e}</h3>"
    finally:
        cursor.close()
        conn.close()


@app.route('/dashboard/export')
def dashboard_export():
    """Stream all student records for a degree+class as a downloadable CSV."""
    degree         = request.args.get('degree', '').strip()
    student_class  = request.args.get('class', '').strip()

    if not degree or not student_class:
        return Response("Missing degree or class parameter.", status=400)

    conn = get_db_connection()
    if not conn:
        return Response("Database connection failed.", status=500)

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, student_name, student_class, degree, gender,
                   cgpa, internships, projects, coding_skills,
                   communication_skills, aptitude_test_score, backlogs,
                   prediction_result, probability, created_at
            FROM predictions
            WHERE degree = %s AND student_class = %s
            ORDER BY created_at DESC
        """, (degree, student_class))
        rows = cursor.fetchall()

        # Build CSV in-memory
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            'id', 'student_name', 'student_class', 'degree', 'gender',
            'cgpa', 'internships', 'projects', 'coding_skills',
            'communication_skills', 'aptitude_test_score', 'backlogs',
            'prediction_result', 'probability', 'created_at'
        ])
        writer.writeheader()
        for row in rows:
            # Convert datetime to readable string
            if isinstance(row.get('created_at'), datetime):
                row['created_at'] = row['created_at'].strftime('%Y-%m-%d %H:%M:%S')
            writer.writerow(row)

        csv_data = output.getvalue()
        output.close()

        filename = f"{degree}_{student_class}_predictions.csv".replace(' ', '_')
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