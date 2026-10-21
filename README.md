# Grade 7 Science Assessment — Separation Techniques

Streamlit website with 15 questions, automatically graded answers, private teacher dashboard, SQLite for local use, PostgreSQL for hosted use, and Excel exports. No student accounts required.

## 1. Run locally

1. Install Python 3.10 or newer.
2. Open a terminal in this project folder.
3. Install dependencies (prefer a virtual environment):

   ```bash
   python -m venv .venv
   # macOS/Linux: source .venv/bin/activate
   # Windows PowerShell: .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
4. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`.
5. Edit the private copy so `TEACHER_USERNAME = "cyoussef"` and `TEACHER_PASSWORD` is the password supplied in your request (`kouki20`). Keep this file private; the sample intentionally does **not** contain a usable password.
6. Start the website:

   ```bash
   streamlit run app.py
   ```
7. Open the URL printed in the terminal (usually `http://localhost:8501`). Students choose a class, enter a full name, and submit; teacher uses **Teacher Login**.

Locally the grade records are stored in `grades.sqlite3` (created automatically). **Back up this file** to preserve historical grades. Do not share it or commit it to Git.

## 2. Make changes without touching Python

- Edit `config.json` to change assessment title, topic, passing grade (0–100), class list, or whether students can type a custom class.
- Edit `questions.json` to add/edit/delete questions. Keep unique `id` values. The number of questions and final percentage are automatic.
- Supported types: `multiple_choice` (options + string answer), `true_false` (boolean answer), `matching` (dictionary of pairs + possible options). Each matching question is worth one point **only when all its pairs are correct**.
- Change teacher credentials only in private Streamlit Secrets/environment variables, **not** `config.json` or public Python/JSON files.
- Changes to questions affect future new attempts. Avoid editing question IDs while students are mid-assessment; restart fresh attempts after changing question files.

## 3. Deploy online with persistent storage (Streamlit Community Cloud)

**Important:** Streamlit Community Cloud's local filesystem is ephemeral. Never rely on SQLite there for lasting grades. Configure a **hosted PostgreSQL database**, for example from Neon, Supabase, or a managed PostgreSQL provider.

1. Create a private PostgreSQL database with a provider. Obtain the **server-side** connection string; ensure SSL is enabled as required by your provider and restrict database access to only that app's credentials.
2. Create a GitHub repository containing `app.py`, `config.json`, `questions.json`, `requirements.txt`, `.gitignore`, `README.md`, and `.streamlit/secrets.toml.example`. **Do not upload** `.streamlit/secrets.toml`, a `.db`/`.sqlite3` file, grade exports, or any real grade data.
3. Visit [share.streamlit.io](https://share.streamlit.io/), connect GitHub, select the repository, and use `app.py` as the entry point.
4. Before launching the deployed site, use Streamlit Community Cloud **App settings → Secrets** and enter these values (fill in the real private connection string):

   ```toml
   TEACHER_USERNAME = "cyoussef"
   TEACHER_PASSWORD = "<your-private-password>"
   DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"
   ```

   If your provider gives `postgresql://...`, change the prefix to `postgresql+psycopg://...` to use the installed driver. URL-encode special characters in usernames/passwords. Use the SSL requirements your provider specifies.
5. Deploy, submit a test attempt, log into the teacher dashboard, download the Excel gradebook, then reboot the app and confirm the test record remains.
6. Configure backups, database retention, restricted provider permissions, and access control according to your school's policies. **Remove any practice grades before going live** if needed.

## 4. How records and exports work

Each attempt receives a UUID (unique database primary key). Saving is one atomic insert; refreshing or double-clicking does not insert a second grade for the same attempt. Each *new* assessment attempt has a new UUID. The app does **not** identify a returning student by their name alone; students could intentionally take another attempt. Add accounts or a teacher-issued single-use code if you require one submission per student across all devices.

Stored columns: full name, class, correct answers, total questions, percentage, UTC submission time, and attempt UUID. The dashboard displays them, with a class filter. The Excel workbook has exactly one sheet, **Student Grades**, and three columns, **Student Name**, **Class**, and **Score (%)**. Numeric percentage values are correctly formatted, and the workbook is generated in memory. Grade exports are only served to an authenticated session via the dashboard; no public static gradebook URL is created.

## 5. Important security notes

- A teacher-login form and Streamlit session authentication protect the teacher dashboard and export feature at the application level. Host the service using HTTPS and keep secrets and database credentials private.
- The specified teacher password is weak for a public school site. Replace it with a long, unique password before putting real pupil records online. This example has no cross-session login throttling, MFA, or school SSO; add them for sensitive, high-stakes use.
- The app does not display gradebook data on student screens. After submitting, students see the score only within their own current browser session. The session is not an authenticated identity, so **do not use shared browsers** for private results; any person using the same open session may see that student's score.
- `questions.json` contains answer keys; if you publish the source to a public GitHub repository, students can inspect them. Use a **private source repository where supported** or move answer keys to teacher-only secure storage if exam integrity matters. Make sure your deployment provider's repository access policy supports private repositories.
- There is no user-account verification: a student can type another person's name. For real graded school assessment, consider teacher-issued codes or identity verification.
- Excel workbook files are **not password-encrypted** after download. Teachers must store exports securely.
- If `DATABASE_URL` is not set, the app intentionally falls back to local SQLite **for development only**. Configure PostgreSQL on Community Cloud before inviting students.
