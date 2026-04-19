from flask import Flask, render_template, request
import pickle
import numpy as np
import os

app = Flask(__name__)

#  Load model (keep model.pkl in same folder as app.py)
MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")
model = pickle.load(open(MODEL_PATH, "rb"))

#  Encoding mappings
GENDER_MAP = {'Male': 1, 'Female': 0}
DEGREE_MAP = {'B.Tech': 1, 'BCA': 2, 'MCA': 3, 'B.Sc': 0}

#  Recommendation function
def recommend(student):
    recs = []

    if student["CGPA"] < 6:
        recs.append("Improve CGPA")
    if student["Coding_Skills"] < 6:
        recs.append("Practice coding (DSA)")
    if student["Communication_Skills"] < 6:
        recs.append("Improve communication skills")
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

#  Home route
@app.route('/')
def home():
    return render_template("index.html")

#  Prediction route
@app.route('/predict', methods=['POST'])
def predict():
    try:
        form = request.form

        #  Encode categorical inputs
        gender = GENDER_MAP.get(form["Gender"], 1)
        degree = DEGREE_MAP.get(form["Degree"], 1)

        #  Prepare data (⚠️ must match training order)
        data = np.array([[ 
            float(form["Age"]),
            gender,
            degree,
            float(form["CGPA"]),
            float(form["Internships"]),
            float(form["Projects"]),
            float(form["Coding_Skills"]),
            float(form["Communication_Skills"]),
            float(form["Aptitude_Test_Score"]),
            float(form["Backlogs"])
        ]])

        #  Prediction
        prediction = model.predict(data)[0]
        prob = model.predict_proba(data)[0][1]

        result = "Placed" if prediction == 1 else "Not Placed"

        #  Recommendation input
        student = {
            "CGPA": float(form["CGPA"]),
            "Coding_Skills": float(form["Coding_Skills"]),
            "Communication_Skills": float(form["Communication_Skills"]),
            "Aptitude_Test_Score": float(form["Aptitude_Test_Score"]),
            "Internships": float(form["Internships"]),
            "Projects": float(form["Projects"]),
            "Backlogs": float(form["Backlogs"])
        }

        recs = recommend(student)

        #  Show result page (better UI)
        return render_template(
            "result.html",
            prediction=result,
            probability=round(prob * 100, 2),
            recommendations=recs
        )

    except Exception as e:
        return f"Error: {str(e)}"

#  Run app
if __name__ == "__main__":
    app.run(debug=True)