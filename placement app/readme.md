# 🎓 Student Placement Prediction System

A Machine Learning-based web application that predicts whether a student will be placed or not based on academic performance, skills, and experience.

---

## 🚀 Project Overview

This project uses a **Random Forest Classifier** to analyze student data and predict placement chances.
It also provides **personalized recommendations** to improve placement probability.

---

## 🧠 Features

* 📊 Predict placement (Placed / Not Placed)
* 📈 Show placement probability (%)
* 💡 AI-based recommendations for improvement
* 🌐 Interactive web UI (Flask + HTML + CSS)
* ⚡ Real-time prediction

---

## 🛠️ Tech Stack

* **Frontend:** HTML, CSS
* **Backend:** Python (Flask)
* **Machine Learning:** Scikit-learn (Random Forest)
* **Dataset:** Kaggle
* **Model Format:** `.pkl`

---

## 📂 Project Structure

```
placement-app/
│
├── app.py
├── md.pkl
│
├── static/
│   └── css/
│       ├── style.css
│       └── result.css
│
├── templates/
│   ├── index.html
│   └── result.html
│
└── notebooks/
    └── model.ipynb
```

---

## ⚙️ Features Used in Model

```
CGPA
Internships
Projects
Coding_Skills
Communication_Skills
Aptitude_Test_Score
Backlogs
Degree
Gender
avg_score
total_skills
is_weak
```

### 🔍 Feature Engineering

* **avg_score** = (CGPA + Internships + Projects) / 3
* **total_skills** = Aptitude + Coding + Communication
* **is_weak** = 1 if CGPA < 6 else 0

---

## 🧪 Model Training

* Algorithm: **Random Forest Classifier**
* Train-Test Split: 80-20
* Evaluation:

  * Accuracy Score
  * Classification Report

---

## ▶️ How to Run the Project

### 1. Clone Repository

```
git clone https://github.com/your-username/placement-prediction-system.git
cd placement-app
```

### 2. Install Requirements

```
pip install flask numpy scikit-learn
```

### 3. Run Application

```
python app.py
```

### 4. Open in Browser

```
http://127.0.0.1:5000/
```

---

## 🧾 Workflow

1. User enters details in form
2. Data is sent to Flask backend
3. Features are processed
4. Model predicts result
5. Output + recommendations displayed

---

## 🏗️ System Architecture

```
User (Web Form)
      ↓
Flask Backend (app.py)
      ↓
ML Model (md.pkl)
      ↓
Prediction Result + Recommendations
```

---

## 📊 Sample Output

* ✅ Placed (85.34%)
* ❌ Not Placed (42.12%)

---

## 💡 Recommendations Logic

* Low CGPA → Improve academics
* Low Coding → Practice DSA
* Low Communication → Improve speaking
* No Internship → Gain experience
* Backlogs → Clear subjects

---

## ✅ Advantages

* Easy to use
* Real-time prediction
* Helps students improve profile
* Interactive UI

---

## ⚠️ Limitations

* Depends on dataset quality
* Limited real-world factors
* Model accuracy can be improved

---

## 🔮 Future Scope

* Add more features (certifications, branch, soft skills)
* Deploy on cloud (AWS / Render)
* Use Deep Learning models
* Add login system

---

## 👨‍💻 Author

**Pratik Mohite**
B.Tech Computer Science

---

## 📌 Conclusion

This project demonstrates how Machine Learning can be used to solve real-world problems like student placement prediction.
It helps students understand their strengths and improve their chances of getting placed.

---
