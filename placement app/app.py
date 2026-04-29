from flask import Flask, render_template, request
import pickle
import numpy as np
import os

app = Flask(__name__)

# Load model
MODEL_PATH = os.path.join(os.path.dirname(__file__), "md.pkl")
model = pickle.load(open(MODEL_PATH, "rb"))

# Encoding
GENDER_MAP = {'Male': 1, 'Female': 0}
DEGREE_MAP = {'B.Tech': 1, 'BCA': 2, 'MCA': 3, 'B.Sc': 0}

# Recommendation
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

    if len(recs) == 0:
        recs.append("You are on track")

    return recs

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/predict', methods=['POST'])
def predict():
    try:
        form = request.form

        # Inputs
        cgpa = float(form["CGPA"])
        internships = float(form["Internships"])
        projects = float(form["Projects"])
        coding = float(form["Coding_Skills"])
        comm = float(form["Communication_Skills"])
        aptitude = float(form["Aptitude_Test_Score"])
        backlogs = float(form["Backlogs"])

        gender = GENDER_MAP.get(form["Gender"], 1)
        degree = DEGREE_MAP.get(form["Degree"], 1)

        #  Feature Engineering (same as training)
        avg_score = (cgpa + internships + projects) / 3
        total_skills = aptitude + comm + coding
        is_weak = 1 if cgpa < 6 else 0

        #  Correct order (12 features)
        data = np.array([[ 
            cgpa,
            internships,
            projects,
            coding,
            comm,
            aptitude,
            backlogs,
            degree,
            gender,
            avg_score,
            total_skills,
            is_weak
        ]])

        prediction = model.predict(data)[0]
        prob = model.predict_proba(data)[0][1]

        result = "Placed" if prediction == 1 else "Not Placed"

        student = {
            "CGPA": cgpa,
            "Coding_Skills": coding,
            "Communication_Skills": comm,
            "Aptitude_Test_Score": aptitude,
            "Internships": internships,
            "Projects": projects,
            "Backlogs": backlogs
        }

        recs = recommend(student)

        return render_template(
            "result.html",
            prediction=result,
            probability=round(prob * 100, 2),
            recommendations=recs
        )

    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == "__main__":
    app.run(debug=True)