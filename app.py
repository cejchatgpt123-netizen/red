"""Grade 7 Science assessment: Streamlit + SQLite/PostgreSQL + teacher-only Excel."""
from __future__ import annotations

import hmac
import io
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl.styles import Alignment, Font, PatternFill
from sqlalchemy import Column, DateTime, Float, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parent


def read_settings():
    with (ROOT / "config.json").open(encoding="utf-8") as file:
        return json.load(file)


def read_questions():
    with (ROOT / "questions.json").open(encoding="utf-8") as file:
        questions = json.load(file)
    ids = [q["id"] for q in questions]
    if len(ids) != len(set(ids)) or not questions:
        raise ValueError("Question IDs must be unique and questions.json cannot be empty.")
    for q in questions:
        if q["type"] == "multiple_choice":
            if q["answer"] not in q["options"]:
                raise ValueError(f"Invalid answer in {q['id']}")
        elif q["type"] == "true_false":
            if type(q["answer"]) is not bool:
                raise ValueError(f"Expected boolean answer in {q['id']}")
        elif q["type"] == "matching":
            if not q["pairs"] or any(a not in q["options"] for a in q["pairs"].values()):
                raise ValueError(f"Invalid matching question {q['id']}")
        else:
            raise ValueError(f"Unknown question type in {q['id']}")
    return questions


def secret(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name)
        if value is not None:
            return str(value)
    except (FileNotFoundError, OSError):
        pass
    return os.getenv(name, default)


metadata = MetaData()
grades = Table(
    "grades", metadata,
    Column("attempt_id", String(36), primary_key=True),
    Column("student_name", String(100), nullable=False),
    Column("class_name", String(60), nullable=False),
    Column("correct_answers", Integer, nullable=False),
    Column("total_questions", Integer, nullable=False),
    Column("score_percent", Float, nullable=False),
    Column("submitted_at", DateTime(timezone=True), nullable=False),
)


@st.cache_resource(show_spinner=False)
def database_engine(db_url: str):
    engine = create_engine(db_url, pool_pre_ping=True)
    metadata.create_all(engine)
    return engine


def save_grade(engine, record):
    """One atomic insert; unique attempt_id prevents duplicate grades on reruns."""
    try:
        with engine.begin() as connection:
            connection.execute(grades.insert().values(**record))
        return True
    except IntegrityError:
        return False


def load_grades(engine):
    with engine.connect() as connection:
        rows = connection.execute(select(grades).order_by(grades.c.submitted_at.desc())).mappings().all()
    return pd.DataFrame([dict(row) for row in rows])


def export_excel(frame: pd.DataFrame) -> bytes:
    """Build in memory. Never save gradebook in a public web directory."""
    sheet_data = pd.DataFrame({
        "Student Name": frame["student_name"] if not frame.empty else pd.Series(dtype=str),
        "Class": frame["class_name"] if not frame.empty else pd.Series(dtype=str),
        "Score (%)": frame["score_percent"].astype(float).div(100) if not frame.empty else pd.Series(dtype=float),
    })
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        sheet_data.to_excel(writer, sheet_name="Student Grades", index=False)
        sheet = writer.sheets["Student Grades"]
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for column, width in {"A": 32, "B": 20, "C": 18}.items():
            sheet.column_dimensions[column].width = width
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="164E63")
            cell.alignment = Alignment(horizontal="center")
        for row in sheet.iter_rows(min_row=2, min_col=3, max_col=3):
            row[0].number_format = "0.0%"
    return buffer.getvalue()


def is_answer_correct(question, answer):
    if question["type"] == "matching":
        return isinstance(answer, dict) and all(answer.get(k) == v for k, v in question["pairs"].items())
    return answer == question["answer"]


def full_answer(question):
    if question["type"] == "matching":
        return "; ".join(f"{key} → {value}" for key, value in question["pairs"].items())
    if question["type"] == "true_false":
        return "True" if question["answer"] else "False"
    return question["answer"]


def init_session():
    defaults = {"screen": "welcome", "authenticated": False, "attempt": None,
                "submitted": False, "result": None, "answers": {}, "login_failures": 0}
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def go_home():
    st.session_state.screen = "welcome"
    st.rerun()


def welcome(config, questions):
    st.title(f"🔬 {config['assessment_title']}")
    st.subheader(config["topic"])
    st.write(f"Answer {len(questions)} questions. Your grade is saved automatically when you submit.")
    with st.form("student_details"):
        name = st.text_input("Full Name *", max_chars=100, placeholder="First and last name")
        classes = config.get("classes", [])
        if config.get("allow_custom_class", False):
            section = st.text_input("Class / Section *", max_chars=60)
        else:
            section = st.selectbox("Class / Section *", ["Choose your class..."] + classes)
        start = st.form_submit_button("Start Assessment", type="primary", use_container_width=True)
    if start:
        name = " ".join(name.split())
        section = section.strip()
        if not (2 <= len(name) <= 100) or not re.fullmatch(r"[^<>\x00-\x1f]{2,100}", name):
            st.error("Please enter your full name (2–100 valid characters).")
        elif not section or section == "Choose your class..." or len(section) > 60 or any(c in section for c in "<>\n\r"):
            st.error("Please enter or choose a valid class.")
        else:
            import random
            question_ids = [q["id"] for q in questions]
            random.SystemRandom().shuffle(question_ids)
            st.session_state.attempt = {"id": str(uuid.uuid4()), "name": name,
                                        "class": section, "order": question_ids}
            st.session_state.submitted = False
            st.session_state.result = None
            st.session_state.answers = {}
            st.session_state.screen = "assessment"
            st.rerun()
    st.divider()
    if st.button("Teacher Login", use_container_width=True):
        st.session_state.screen = "teacher"
        st.rerun()


def render_question(q, number):
    st.markdown(f"**Question {number}: {q['question']}**")
    key = f"ans_{st.session_state.attempt['id']}_{q['id']}"
    if q["type"] == "multiple_choice":
        return st.radio("Choose one answer", q["options"], index=None, key=key)
    if q["type"] == "true_false":
        selection = st.radio("Choose True or False", ["True", "False"], index=None, key=key)
        return None if selection is None else selection == "True"
    answers = {}
    for index, prompt in enumerate(q["pairs"]):
        answers[prompt] = st.selectbox(prompt, q["options"], index=None, key=f"{key}_{index}", placeholder="Choose a match")
    return answers


def assessment(config, questions, engine):
    attempt = st.session_state.attempt
    if not attempt:
        go_home()
    st.title(config["assessment_title"])
    st.caption(f"{attempt['name']} · {attempt['class']} · {config['topic']}")
    question_lookup = {q["id"]: q for q in questions}
    ordered = [question_lookup[qid] for qid in attempt["order"] if qid in question_lookup]
    if st.session_state.submitted:
        result = st.session_state.result
        if result is None:
            st.info("This assessment has already been submitted. Please ask your teacher if you need your score.")
            return
        st.metric("Your score", f"{result['percent']:.1f}%")
        st.write(f"**{result['correct']} out of {result['total']} correct**")
        st.success("You passed! Great work.") if result["percent"] >= config["passing_grade_percent"] else st.info("Keep practicing. You can learn from the explanations below.")
        st.subheader("Your feedback")
        for number, q in enumerate(ordered, 1):
            is_correct = is_answer_correct(q, result["answers"].get(q["id"]))
            with st.expander(f"{'✅' if is_correct else '❌'} Question {number}: {q['question']}"):
                st.write("Correct answer:", full_answer(q))
                st.write(q["explanation"])
        if st.button("Return to Welcome"):
            go_home()
        return
    st.progress(0, text=f"{len(ordered)} questions · complete all questions before submitting")
    with st.form("assessment_form"):
        submitted_answers = {}
        for number, q in enumerate(ordered, 1):
            submitted_answers[q["id"]] = render_question(q, number)
            st.divider()
        submitted = st.form_submit_button("Submit Assessment", type="primary", use_container_width=True)
    if submitted:
        if any(a is None or (isinstance(a, dict) and any(v is None for v in a.values())) for a in submitted_answers.values()):
            st.error("Please answer every question and every matching item before submitting.")
            return
        # All option widgets are constrained, but validate again before writing.
        for q in ordered:
            answer = submitted_answers[q["id"]]
            if q["type"] == "multiple_choice" and answer not in q["options"]:
                st.error("Invalid answer detected.")
                return
            if q["type"] == "matching" and (set(answer) != set(q["pairs"]) or any(v not in q["options"] for v in answer.values())):
                st.error("Invalid matching answer detected.")
                return
        correct = sum(is_answer_correct(q, submitted_answers[q["id"]]) for q in ordered)
        total = len(ordered)
        percent = round(100 * correct / total, 2)
        record = {"attempt_id": attempt["id"], "student_name": attempt["name"],
                  "class_name": attempt["class"], "correct_answers": correct,
                  "total_questions": total, "score_percent": percent,
                  "submitted_at": datetime.now(timezone.utc)}
        try:
            inserted = save_grade(engine, record)
        except Exception:
            st.error("Your submission could not be saved. Please retry. Your answers are still on this page.")
            return
        st.session_state.submitted = True
        st.session_state.result = {"correct": correct, "total": total, "percent": percent,
                                   "answers": submitted_answers} if inserted else None
        st.rerun()


def teacher_screen(engine):
    st.title("🔐 Teacher Dashboard")
    if not st.session_state.authenticated:
        st.write("Teacher access only. Students should use the Welcome page.")
        with st.form("teacher_login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            login = st.form_submit_button("Log In", type="primary")
        if login:
            expected_user, expected_password = secret("TEACHER_USERNAME"), secret("TEACHER_PASSWORD")
            valid = bool(expected_user and expected_password) and (
                hmac.compare_digest(username.encode(), expected_user.encode()) &
                hmac.compare_digest(password.encode(), expected_password.encode())
            )
            if valid:
                st.session_state.authenticated = True
                st.session_state.login_failures = 0
                st.rerun()
            else:
                st.session_state.login_failures += 1
                st.error("Incorrect username or password.")
        if st.button("Back to Welcome"):
            go_home()
        return
    if st.button("Log Out"):
        st.session_state.authenticated = False
        go_home()
    try:
        frame = load_grades(engine)
    except Exception:
        st.error("Could not load grades from the database.")
        return
    st.metric("Completed assessments", len(frame))
    if frame.empty:
        st.info("No completed assessments yet.")
        return
    classes = sorted(frame["class_name"].unique().tolist())
    selected = st.selectbox("Filter by class", ["All Classes"] + classes)
    filtered = frame if selected == "All Classes" else frame[frame["class_name"] == selected]
    table = filtered[["student_name", "class_name", "correct_answers", "total_questions", "score_percent", "submitted_at"]].rename(columns={
        "student_name": "Student Name", "class_name": "Class", "correct_answers": "Correct",
        "total_questions": "Total", "score_percent": "Score (%)", "submitted_at": "Submitted (UTC)"})
    st.dataframe(table, hide_index=True, use_container_width=True)
    # Both exports are inside the authenticated branch, generated only on request.
    st.download_button("Download Complete Gradebook (Excel)", data=export_excel(frame),
                       file_name="Grade7_Science_Assessment_Results.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
    if selected != "All Classes":
        st.download_button(f"Download {selected} Grades (Excel)", data=export_excel(filtered),
                           file_name=f"Grade7_Science_{re.sub(r'[^A-Za-z0-9_-]', '_', selected)}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)


def main():
    st.set_page_config(page_title="Grade 7 Science Assessment", page_icon="🔬", layout="centered")
    st.markdown("""<style>
      .block-container {max-width: 860px; padding-top: 2rem}
      h1 {color: #155e75}
      div[data-testid="stForm"] {border: 1px solid #cbd5e1; border-radius: 14px; padding: 18px}
      </style>""", unsafe_allow_html=True)
    init_session()
    try:
        config, questions = read_settings(), read_questions()
        db_url = secret("DATABASE_URL") or f"sqlite:///{ROOT / 'grades.sqlite3'}"
        engine = database_engine(db_url)
    except Exception:
        st.error("Application setup failed. Ask the teacher to check configuration and database settings.")
        st.stop()
    if st.session_state.screen == "teacher":
        teacher_screen(engine)
    elif st.session_state.screen == "assessment":
        assessment(config, questions, engine)
    else:
        welcome(config, questions)


if __name__ == "__main__":
    main()
