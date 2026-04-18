from flask import Flask, render_template, request
import pickle
import numpy as np

app = Flask(__name__)

# Load model
model = pickle.load(open("C:/Datamines/MEGA/placement app/model.pkl", "rb"))

# Recommendation function
def recommend(student):
    recs = []

    if student["CGPA"] < 6:
        recs.append("Improve CGPA")
    if student["Coding_Skills"] < 60:
        recs.append("Practice coding")
    if student["Communication_Skills"] < 60:
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

    form = request.form

    # Model input (IMPORTANT: same order as training)
    data = np.array([[ 
        float(form["Age"]),
        float(form["Gender"]),
        float(form["Degree"]),
        float(form["CGPA"]),
        float(form["Internships"]),
        float(form["Projects"]),
        float(form["Coding_Skills"]),
        float(form["Communication_Skills"]),
        float(form["Aptitude_Test_Score"]),
        float(form["Backlogs"])
    ]])

    prediction = model.predict(data)[0]
    prob = model.predict_proba(data)[0][1]

    result = "Placed" if prediction == 1 else "Not Placed"

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

    return render_template("index.html",
        prediction_text=f"{result} ({round(prob*100,2)}%)",
        recommendations=recs)

if __name__ == "__main__":
    app.run(debug=True)