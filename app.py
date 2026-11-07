
import os
import re
import json
import sqlite3
import pandas as pd
import gradio as gr
import sqlglot

from sqlglot import exp
from google import genai
from google.genai.errors import ServerError, ClientError

API_KEY = os.environ.get("GEMINI_API_KEY")

if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is missing.")

client = genai.Client(api_key=API_KEY)

DB_PATH = os.path.join(os.path.dirname(__file__), "college.db")

PRIMARY_MODEL = "gemini-3.5-flash"
FALLBACK_MODEL = "gemini-3.5-flash-lite"

STUDENTS = [
    (1001,"Aarav Sharma","Computer Science",4,"aarav@college.edu"),
    (1002,"Diya Patel","Computer Science",3,"diya@college.edu"),
    (1003,"Kabir Mehta","Information Technology",4,"kabir@college.edu"),
    (1004,"Ananya Iyer","Electronics",2,"ananya@college.edu"),
    (1005,"Rohan Desai","Computer Science",4,"rohan@college.edu"),
    (1006,"Meera Nair","Information Technology",3,"meera@college.edu"),
    (1007,"Ishaan Kulkarni","Electronics",4,"ishaan@college.edu"),
    (1008,"Sara Khan","Computer Science",2,"sara@college.edu"),
    (1009,"Vivaan Joshi","Information Technology",2,"vivaan@college.edu"),
    (1010,"Aditi Rao","Electronics",3,"aditi@college.edu"),
    (1011,"Arjun Verma","Computer Science",3,"arjun@college.edu"),
    (1012,"Myra Shah","Information Technology",4,"myra@college.edu")
]

COURSES = [
    ("CS101","Database Management Systems",4),
    ("CS102","Artificial Intelligence",3),
    ("CS103","Operating Systems",4),
    ("IT201","Computer Networks",3),
    ("EC301","Digital Electronics",3)
]

MARKS = [
    (1001,"CS101",92),(1001,"CS102",88),(1001,"CS103",85),
    (1002,"CS101",78),(1002,"CS102",91),(1002,"CS103",82),
    (1003,"CS101",85),(1003,"CS102",79),(1003,"IT201",90),
    (1004,"CS101",72),(1004,"EC301",81),(1004,"CS103",76),
    (1005,"CS101",95),(1005,"CS102",93),(1005,"CS103",89),
    (1006,"CS101",88),(1006,"CS102",84),(1006,"IT201",86),
    (1007,"CS101",67),(1007,"EC301",74),(1007,"CS103",80),
    (1008,"CS101",65),(1008,"CS102",72),(1008,"CS103",35),
    (1009,"CS101",81),(1009,"CS102",77),(1009,"IT201",83),
    (1010,"CS101",89),(1010,"EC301",92),(1010,"CS103",87),
    (1011,"CS101",76),(1011,"CS102",80),(1011,"CS103",74),
    (1012,"CS101",90),(1012,"CS102",86),(1012,"IT201",94)
]

def initialize_database():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            student_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            year INTEGER NOT NULL,
            email TEXT UNIQUE
        );

        CREATE TABLE IF NOT EXISTS courses (
            course_id TEXT PRIMARY KEY,
            course_name TEXT NOT NULL,
            credits INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS enrollments (
            enrollment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id TEXT NOT NULL,
            UNIQUE(student_id, course_id),
            FOREIGN KEY(student_id) REFERENCES students(student_id),
            FOREIGN KEY(course_id) REFERENCES courses(course_id)
        );

        CREATE TABLE IF NOT EXISTS marks (
            mark_id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            course_id TEXT NOT NULL,
            marks REAL NOT NULL CHECK(marks BETWEEN 0 AND 100),
            FOREIGN KEY(student_id) REFERENCES students(student_id),
            FOREIGN KEY(course_id) REFERENCES courses(course_id)
        );
        """)

        if conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] == 0:
            conn.executemany("INSERT INTO students VALUES (?,?,?,?,?)", STUDENTS)
            conn.executemany("INSERT INTO courses VALUES (?,?,?)", COURSES)

            enrollments = list({(s,c) for s,c,m in MARKS})

            conn.executemany(
                "INSERT INTO enrollments (student_id,course_id) VALUES (?,?)",
                enrollments
            )

            conn.executemany(
                "INSERT INTO marks (student_id,course_id,marks) VALUES (?,?,?)",
                MARKS
            )

initialize_database()

DATABASE_SCHEMA = {
    "students": ["student_id","name","department","year","email"],
    "courses": ["course_id","course_name","credits"],
    "enrollments": ["enrollment_id","student_id","course_id"],
    "marks": ["mark_id","student_id","course_id","marks"]
}

def generate_sql(question):
    prompt = f"""
Convert the user's question into one SQLite SELECT query.

Schema:
{json.dumps(DATABASE_SCHEMA)}

Rules:
- Only one SELECT statement.
- Use only the given tables and columns.
- Use correct JOIN conditions.
- No INSERT, UPDATE, DELETE, DROP, CREATE, ALTER or PRAGMA.
- Return UNSUPPORTED if the database cannot answer.
- Return SQL only.

Question: {question}
"""

    for model in [PRIMARY_MODEL, FALLBACK_MODEL]:
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt
            )

            sql = response.text.strip()
            sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.I)
            sql = re.sub(r"\s*```$", "", sql)
            return sql.strip()

        except (ServerError, ClientError):
            continue

    raise RuntimeError("Gemini models are temporarily unavailable.")

def validate_sql(sql):
    if sql.strip().upper() == "UNSUPPORTED":
        raise ValueError("Question is not supported by this database.")

    statements = sqlglot.parse(sql, read="sqlite")

    if len(statements) != 1 or statements[0] is None:
        raise ValueError("Only one SQL statement is allowed.")

    statement = statements[0]

    if not isinstance(statement, exp.Select):
        raise ValueError("Only SELECT queries are allowed.")

    forbidden = (
        exp.Insert, exp.Update, exp.Delete, exp.Drop,
        exp.Create, exp.Alter, exp.Command
    )

    for node in statement.walk():
        if isinstance(node, forbidden):
            raise ValueError("Unsafe SQL operation detected.")

    return statement.sql(dialect="sqlite")

def execute_safe_sql(sql):
    validated_sql = validate_sql(sql)

    conn = sqlite3.connect(
        f"file:{DB_PATH}?mode=ro",
        uri=True
    )

    try:
        conn.execute("PRAGMA query_only = ON")
        conn.set_progress_handler(
            lambda: 1, 500000
        ) if False else None

        return pd.read_sql_query(validated_sql, conn)

    finally:
        conn.close()

def campusquery_app(question):
    if not question or not question.strip():
        return "Please enter a question.", "", pd.DataFrame(), None

    try:
        sql = generate_sql(question)
        result = execute_safe_sql(sql)

        csv_path = "/tmp/campusquery_results.csv"
        result.to_csv(csv_path, index=False)

        return "Query executed successfully!", sql, result, csv_path

    except Exception as error:
        return f"Error: {str(error)}", "", pd.DataFrame(), None

with gr.Blocks(
    title="CampusQuery AI",
    theme=gr.themes.Soft()
) as demo:

    gr.Markdown("""
    # 🎓 CampusQuery AI
    ### Ask questions about college data in plain English

    Convert natural language into SQL using Gemini AI and SQLite.
    """)

    question = gr.Textbox(
        label="Enter your question",
        placeholder="Show all students from Computer Science department.",
        lines=2
    )

    submit = gr.Button("Generate SQL & Run Query", variant="primary")

    status = gr.Textbox(label="Execution Status")
    generated_sql = gr.Code(label="Generated SQL", language="sql")
    results = gr.Dataframe(label="Query Results")
    download = gr.File(label="Download CSV")

    gr.Examples(
        examples=[
            ["Show all students from Computer Science department."],
            ["Find the top 5 students with the highest average marks."],
            ["Calculate average marks for each department."],
            ["Find students who failed any subject."],
            ["Show the marks of Aarav Sharma across all subjects."]
        ],
        inputs=question
    )

    submit.click(
        campusquery_app,
        inputs=question,
        outputs=[status, generated_sql, results, download]
    )

    question.submit(
        campusquery_app,
        inputs=question,
        outputs=[status, generated_sql, results, download]
    )

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
