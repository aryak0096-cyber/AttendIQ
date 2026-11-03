import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import hashlib
import math
from datetime import date
from urllib.parse import quote
import plotly.express as px
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_absolute_error
from sklearn.model_selection import train_test_split

st.set_page_config(page_title="AttendIQ | IMED BCA Sem V", layout="wide")

st.markdown(
    """
    <style>
    .block-container {padding-top: 2.2rem; max-width: 1250px;}
    footer {visibility: hidden;}
    [data-testid="stDeployButton"] {display: none;}
    h1 {font-size: 1.7rem !important; font-weight: 650 !important; letter-spacing: -0.01em;}
    h2, h3 {font-weight: 600 !important;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------- CONFIG
DB_FILE = "imed_attendance_v2.db"
INSTITUTE = "Institute of Management and Entrepreneurship Development (IMED), Pune"
UNIVERSITY = "Bharati Vidyapeeth (Deemed to be) University"
CLASS_NAME = "BCA Semester V - Div. A"
SIGNATORY = "Co-ordinator, BCA (IMED)"   # change this line to whoever signs notices

DEFAULT_SEM_TOTAL = 240   # total classes in the whole semester (all subjects together)
DEFAULT_HELD = 120        # classes held so far (admin can change this in the sidebar)
DEFAULT_MIN_PCT = 75      # overall attendance rule

SUBJECT_LABELS = {
    "PythonLab_Attended": "Lab on Python",
    "DotNetLab_Attended": "Lab on C# & .NET",
    "DotNet_Attended": "C# & .NET",
    "PythonProg_Attended": "Python Programming",
    "ED_Attended": "Entrepreneurship Dev.",
    "Elective1_Attended": "Elective I",
    "HumanRights_Attended": "Human Rights",
    "ITApti_Attended": "IT Based Aptitude",
}
SUBJECTS = list(SUBJECT_LABELS.keys())
STUDENT_COLS = ["Roll_No", "Student_Name", "Parent_Phone"] + SUBJECTS + ["Internal_Marks"]
STATUS_COLORS = {"Safe": "#2e7d32", "Defaulter": "#c62828"}


# ---------------------------------------------------------------- DATABASE
def make_seed_students(per_subject=15):
    """Sample (fictional) class list. Replace with real students in the Admin register."""
    rng = np.random.RandomState(7)
    # (roll, name, rough attendance fraction, internal marks, weak subject indexes)
    profile = [
        ("BCA24001", "Aarav Sharma", 0.95, 27, []),
        ("BCA24002", "Priya Patel", 0.76, 21, []),
        ("BCA24003", "Rohan Verma", 0.98, 29, []),
        ("BCA24004", "Sneha Gupta", 0.55, 14, []),
        ("BCA24005", "Vikram Singh", 0.80, 19, [1, 4, 6]),   # selective bunker
        ("BCA24006", "Ananya Roy", 0.86, 25, []),
        ("BCA24007", "Kabir Das", 0.43, 12, []),
        ("BCA24008", "Neha Joshi", 0.80, 24, []),
        ("BCA24009", "Aditya Nair", 0.66, 18, []),
        ("BCA24010", "Pooja Mehta", 0.97, 28, []),
        ("BCA24011", "Rishi Tiwari", 0.60, 16, []),
        ("BCA24012", "Kavya Iyer", 0.92, 26, []),
        ("BCA24013", "Manish Kumar", 0.36, 10, []),
        ("BCA24014", "Divya Choudhury", 0.76, 22, []),
        ("BCA24015", "Saurabh Jain", 0.87, 25, []),
    ]
    rows = []
    for i, (roll, name, frac, internal, weak) in enumerate(profile):
        vals = []
        for j in range(len(SUBJECTS)):
            f = frac + rng.normal(0, 0.05)
            if j in weak:
                f = 0.25 + rng.uniform(0, 0.1)
            elif weak:
                f = 0.97
            vals.append(int(np.clip(round(f * per_subject), 0, per_subject)))
        rows.append((roll, name, f"9198765432{10 + i}", *vals, internal))
    return rows


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    subj_sql = ",\n            ".join(f"{col} INTEGER" for col in SUBJECTS)
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS students (
            Roll_No TEXT PRIMARY KEY,
            Student_Name TEXT,
            Parent_Phone TEXT,
            {subj_sql},
            Internal_Marks INTEGER
        )
    """)
    c.execute("SELECT COUNT(*) FROM students")
    if c.fetchone()[0] == 0:
        marks = ",".join("?" * len(STUDENT_COLS))
        c.executemany(f"INSERT INTO students VALUES ({marks})", make_seed_students())

    c.execute("""
        CREATE TABLE IF NOT EXISTS alumni_training_data (
            Senior_Roll_No TEXT PRIMARY KEY,
            Attendance_Pct REAL,
            Internal_Marks INTEGER,
            Actual_EndSem_Score REAL
        )
    """)
    c.execute("SELECT COUNT(*) FROM alumni_training_data")
    if c.fetchone()[0] == 0:
        # Simulated (synthetic) senior-batch data, seeded so results are repeatable.
        np.random.seed(42)
        past_att = np.random.uniform(45, 98, 60).round(1)
        past_int = np.random.randint(10, 30, 60)
        noise = np.random.normal(0, 3.1, 60)
        final_scores = np.clip((0.42 * past_att) + (1.75 * past_int) + noise, 25, 99).round(1)
        alumni_rows = [
            (f"BCA230{i+1:02d}", float(past_att[i]), int(past_int[i]), float(final_scores[i]))
            for i in range(60)
        ]
        c.executemany("INSERT INTO alumni_training_data VALUES (?,?,?,?)", alumni_rows)

    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()


def get_setting(key, default):
    conn = sqlite3.connect(DB_FILE)
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return type(default)(row[0]) if row else default


def set_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


def load_tables():
    conn = sqlite3.connect(DB_FILE)
    students_df = pd.read_sql_query("SELECT * FROM students", conn)
    alumni_df = pd.read_sql_query("SELECT * FROM alumni_training_data", conn)
    conn.close()
    return students_df, alumni_df


def validate_students(df, held_classes):
    """Clean admin edits. Returns (clean_df, list_of_problems)."""
    problems = []
    cap = math.ceil(held_classes / len(SUBJECTS))
    df = df.copy()[STUDENT_COLS]
    df["Roll_No"] = df["Roll_No"].fillna("").astype(str).str.strip()
    blank = df["Roll_No"].isin(["", "None", "nan"])
    if blank.any():
        problems.append(f"{int(blank.sum())} row(s) without a Roll No were ignored.")
        df = df[~blank]
    dup = df["Roll_No"].duplicated(keep="first")
    if dup.any():
        problems.append(f"Duplicate Roll No removed: {', '.join(df.loc[dup, 'Roll_No'])}")
        df = df[~dup]
    for col in SUBJECTS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
        if (df[col] > cap).any() or (df[col] < 0).any():
            problems.append(f"{SUBJECT_LABELS[col]}: values adjusted to stay between 0 and {cap}.")
        df[col] = df[col].clip(0, cap)
    df["Internal_Marks"] = pd.to_numeric(df["Internal_Marks"], errors="coerce").fillna(0).astype(int).clip(0, 30)
    df["Parent_Phone"] = df["Parent_Phone"].fillna("").astype(str)
    df["Student_Name"] = df["Student_Name"].fillna("").astype(str)
    return df, problems


def save_to_db(df):
    # DELETE + INSERT keeps the table definition (PRIMARY KEY) intact.
    conn = sqlite3.connect(DB_FILE)
    conn.execute("DELETE FROM students")
    df.to_sql("students", conn, if_exists="append", index=False)
    conn.commit()
    conn.close()


def reset_db():
    conn = sqlite3.connect(DB_FILE)
    for t in ("students", "alumni_training_data", "settings"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.commit()
    conn.close()
    init_db()


# ---------------------------------------------------------------- LOGIC
def eligibility(attended, held_classes, sem_total, target_pct):
    """Can this student still finish the semester at target_pct of ALL sem_total classes?
    Returns (classes_needed, classes_can_miss, reachable, max_possible_pct)."""
    required_total = math.ceil(round(target_pct / 100.0 * sem_total, 6))
    remaining_classes = max(0, sem_total - held_classes)
    needed = max(0, required_total - attended)
    reachable = needed <= remaining_classes
    can_miss = min(remaining_classes, max(0, attended + remaining_classes - required_total)) if reachable else 0
    max_pct = (attended + remaining_classes) / sem_total * 100
    return int(needed), int(can_miss), reachable, round(max_pct, 1)


@st.cache_resource
def train_model(alumni_df):
    """Train on 80%, test on the unseen 20% for an honest accuracy, then refit on all data."""
    X = alumni_df[["Attendance_Pct", "Internal_Marks"]].values
    y = alumni_df["Actual_EndSem_Score"].values
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
    check = LinearRegression().fit(X_tr, y_tr)
    pred = check.predict(X_te)
    final_model = LinearRegression().fit(X, y)
    return final_model, r2_score(y_te, pred), mean_absolute_error(y_te, pred)


def run_analytics_and_ml(df, alumni_df, sem_total, held_classes, min_threshold):
    df_calc = df.copy()
    cap = math.ceil(held_classes / len(SUBJECTS))
    share = held_classes / len(SUBJECTS)            # equal share of held classes per subject
    df_calc[SUBJECTS] = df_calc[SUBJECTS].clip(upper=cap)
    df_calc["Total_Attended"] = df_calc[SUBJECTS].sum(axis=1).clip(upper=held_classes)
    df_calc["Total_Classes"] = held_classes
    df_calc["Overall_Pct"] = ((df_calc["Total_Attended"] / held_classes) * 100).round(2)

    # Subject-wise % (equal share per subject) is used only for pattern detection
    sub_pcts = (df_calc[SUBJECTS] / share * 100).clip(upper=100)
    df_calc["Sub_StdDev"] = sub_pcts.std(axis=1).fillna(0).round(1)
    df_calc["Weakest_Subject"] = sub_pcts.idxmin(axis=1).map(SUBJECT_LABELS)
    df_calc["Pattern_Flag"] = np.where(df_calc["Sub_StdDev"] > 18.0, "Selective Bunking", "Normal")

    ml_model, r2_acc, mae = train_model(alumni_df)
    X_current = df_calc[["Overall_Pct", "Internal_Marks"]].values
    df_calc["ML_Predicted_Score"] = np.clip(ml_model.predict(X_current), 0, 100).round(1)

    df_calc["Status"] = np.where(df_calc["Overall_Pct"] >= min_threshold, "Safe", "Defaulter")
    needed, misses, reach, maxp = [], [], [], []
    for _, row in df_calc.iterrows():
        n, m, ok, mp = eligibility(row["Total_Attended"], held_classes, sem_total, min_threshold)
        needed.append(n); misses.append(m); reach.append("Yes" if ok else "No"); maxp.append(mp)
    df_calc["Classes_Needed"] = needed
    df_calc["Safe_Bunks_Left"] = misses
    df_calc["Target_Reachable"] = reach
    df_calc["Max_Possible_Pct"] = maxp
    return df_calc, ml_model, r2_acc, mae, share


def verify_hash(password, target_hash):
    return hashlib.sha256(password.encode()).hexdigest() == target_hash


ADMIN_HASH = hashlib.sha256("admin".encode()).hexdigest()
init_db()
raw_df, alumni_df = load_tables()

# ---------------------------------------------------------------- SIDEBAR
sem_total = get_setting("sem_total", DEFAULT_SEM_TOTAL)
held = get_setting("held", DEFAULT_HELD)
min_req_pct = get_setting("min_pct", DEFAULT_MIN_PCT)
is_admin, student_roll, authed = False, None, True

with st.sidebar:
    st.title("AttendIQ")
    st.caption(f"{CLASS_NAME}  |  IMED, Pune")
    role = st.radio("Sign in as", ["Admin (HOD / Faculty)", "Student"])
    st.divider()
    if role.startswith("Admin"):
        pwd = st.text_input("Password (demo: admin)", type="password", value="admin")
        if verify_hash(pwd, ADMIN_HASH):
            is_admin = True
            st.success("Signed in as Admin")
            st.subheader("Attendance Rules")
            sem_total = int(st.number_input("Total classes in semester", 8, 2000, sem_total, step=8))
            held = int(st.number_input("Classes held so far", 8, sem_total, min(held, sem_total), step=8))
            min_req_pct = int(st.slider("Mandatory attendance (%)", 60, 90, min_req_pct, 5))
            set_setting("sem_total", sem_total)
            set_setting("held", held)
            set_setting("min_pct", min_req_pct)
            st.caption(f"Classes remaining: {sem_total - held}")
            st.divider()
            if st.button("Reset database to defaults", width="stretch"):
                reset_db()
                st.session_state["ver"] = st.session_state.get("ver", 0) + 1
                st.rerun()
        else:
            authed = False
            st.error("Incorrect password")
    else:
        student_roll = st.selectbox("Your Roll No", raw_df["Roll_No"].tolist())
        st.caption("Rules set by the department")
        st.write(f"Classes in semester: **{sem_total}**")
        st.write(f"Held so far: **{min(held, sem_total)}**")
        st.write(f"Mandatory attendance: **{min_req_pct}%**")

if not authed:
    st.title("AttendIQ")
    st.info("Enter the admin password in the sidebar to continue.")
    st.stop()

held = min(held, sem_total)
remaining = sem_total - held
processed_df, ml_model, r2_acc, mae_acc, share = run_analytics_and_ml(raw_df, alumni_df, sem_total, held, min_req_pct)
defaulters_df = processed_df[processed_df["Overall_Pct"] < min_req_pct].sort_values("Overall_Pct")


# ================================================================ STUDENT VIEW
def render_student(roll):
    me = processed_df[processed_df["Roll_No"] == roll].iloc[0]
    class_avg = processed_df["Overall_Pct"].mean()
    feasible = me["Target_Reachable"] == "Yes"
    need, can_miss = int(me["Classes_Needed"]), int(me["Safe_Bunks_Left"])

    st.title("Student Portal")
    st.markdown(f"**{me['Student_Name']}**  |  {me['Roll_No']}  |  {CLASS_NAME}  |  {date.today().strftime('%d %b %Y')}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Attendance so far", f"{me['Overall_Pct']:.1f}%", f"{me['Overall_Pct'] - class_avg:+.1f}% vs class average", border=True)
    m2.metric("Classes attended", f"{int(me['Total_Attended'])} / {held} held", border=True)
    m3.metric("Status", me["Status"], f"Required: {min_req_pct}%", delta_color="off", border=True)
    if feasible:
        m4.metric(f"Must attend (of {remaining} left)", need, border=True)
    else:
        m4.metric("Maximum possible", f"{me['Max_Possible_Pct']:.1f}%", border=True)

    if not feasible:
        st.error(f"Only {remaining} classes remain in the semester. Even with full attendance, the maximum you can reach "
                 f"is {me['Max_Possible_Pct']:.1f}%, below the required {min_req_pct}%. Please meet your faculty coordinator.")
    elif need == 0:
        st.success(f"You have already attended enough classes to meet {min_req_pct}% for the semester.")
    elif me["Status"] == "Safe":
        st.success(f"You are on track. Attend at least {need} of the remaining {remaining} classes "
                   f"(you can miss up to {can_miss}) to finish at {min_req_pct}% or more.")
    else:
        st.warning(f"You are below {min_req_pct}% right now, but it is recoverable. Attend at least {need} of the "
                   f"remaining {remaining} classes (you can miss up to {can_miss}).")
    if me["Pattern_Flag"] != "Normal":
        st.warning(f"Your attendance is uneven across subjects. Weakest subject: {me['Weakest_Subject']}.")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Subject-wise attendance")
        sub_df = pd.DataFrame({
            "Subject": [SUBJECT_LABELS[c] for c in SUBJECTS],
            "Attended": [int(me[c]) for c in SUBJECTS],
        })
        sub_df["Percent"] = (sub_df["Attended"] / share * 100).round(1)
        fig = px.bar(sub_df, x="Percent", y="Subject", orientation="h", text="Percent",
                     range_x=[0, 105], color_discrete_sequence=["#37474f"])
        fig.add_vline(x=min_req_pct, line_dash="dash", line_color="#c62828",
                      annotation_text=f"Required {min_req_pct}%", annotation_position="top")
        fig.update_layout(height=380, margin=dict(l=0, r=0, t=30, b=0), yaxis_title=None, xaxis_title="Attendance %")
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Subject percentages assume an equal share of {share:.0f} classes per subject so far.")
    with right:
        st.subheader("What if I attend / miss?")
        if remaining > 0:
            n = st.slider("Next classes", 0, remaining, min(10, remaining))
            att = float(me["Total_Attended"])
            c1, c2 = st.columns(2)
            c1.metric("Attend all", f"{(att + n) / (held + n) * 100:.1f}%", border=True)
            c2.metric("Miss all", f"{att / (held + n) * 100:.1f}%", border=True)
        else:
            st.info("The semester is complete.")
        st.subheader("Predicted end-sem score")
        score = float(me["ML_Predicted_Score"])
        st.metric("Based on attendance and internals", f"{score:.1f} / 100", border=True)
        if score < 50:
            st.error("High risk. Speak to your faculty coordinator.")
        elif score < 65:
            st.warning("Moderate. More attendance and practice will help.")
        else:
            st.success("On track.")


# ================================================================ ADMIN VIEW
def render_admin():
    st.title("AttendIQ: Attendance Management and Academic Risk")
    st.markdown(
        f"**{UNIVERSITY}  |  {INSTITUTE}**  \n"
        f"{CLASS_NAME}  |  {held} of {sem_total} classes held  |  {remaining} remaining  |  "
        f"{min_req_pct}% required  |  {date.today().strftime('%d %b %Y')}"
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Students", len(processed_df), border=True)
    c2.metric("Average attendance", f"{processed_df['Overall_Pct'].mean():.1f}%", border=True)
    c3.metric(f"Safe (>= {min_req_pct}%)", int((processed_df["Status"] == "Safe").sum()), border=True)
    c4.metric("Defaulters", len(defaulters_df), border=True)
    c5.metric("Cannot reach target", int((processed_df["Target_Reachable"] == "No").sum()), border=True)
    c6.metric("Selective bunking", int((processed_df["Pattern_Flag"] != "Normal").sum()), border=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Register", "Defaulters", "Analytics", "ML Predictor", "Notices"])

    # -------- Register
    with tab1:
        st.subheader("Student register (SQLite)")
        st.caption("Edit any cell or add a row, then click Save. Changes are stored permanently in the database.")
        ver = st.session_state.get("ver", 0)
        cap = math.ceil(held / len(SUBJECTS))
        edited_df = st.data_editor(
            raw_df, num_rows="dynamic", width="stretch", hide_index=True, key=f"sql_editor_{ver}",
            column_config={col_key: st.column_config.NumberColumn(label, min_value=0, max_value=cap)
                           for col_key, label in SUBJECT_LABELS.items()},
        )
        if st.button("Save changes", type="primary"):
            clean_df, problems = validate_students(edited_df, held)
            save_to_db(clean_df)
            st.session_state["ver"] = ver + 1
            for p in problems:
                st.warning(p)
            st.toast("Saved to database")
            if not problems:
                st.rerun()

        st.subheader("Computed view")
        st.dataframe(
            processed_df[["Roll_No", "Student_Name", "Overall_Pct", "Internal_Marks", "ML_Predicted_Score", "Status",
                          "Target_Reachable", "Classes_Needed", "Safe_Bunks_Left", "Pattern_Flag", "Weakest_Subject"]],
            width="stretch", hide_index=True,
        )

    # -------- Defaulters
    with tab2:
        st.subheader("Defaulters and recovery")
        st.caption(f"{remaining} classes remain. Classes needed = classes the student must still attend to finish at "
                   f"{min_req_pct}% of {sem_total}. If that is more than the classes remaining, the target cannot be reached.")
        if defaulters_df.empty:
            st.success("No defaulters under the current rules.")
        st.dataframe(
            defaulters_df[["Roll_No", "Student_Name", "Overall_Pct", "Status", "Classes_Needed", "Target_Reachable",
                           "Max_Possible_Pct", "Pattern_Flag", "Weakest_Subject", "ML_Predicted_Score"]],
            width="stretch", hide_index=True,
        )
        st.download_button("Export defaulter report (CSV)", data=defaulters_df.to_csv(index=False).encode("utf-8"),
                           file_name=f"IMED_BCA_Sem5_Defaulters_{date.today()}.csv", mime="text/csv")

    # -------- Analytics
    with tab3:
        v1, v2 = st.columns(2)
        with v1:
            st.subheader("Subject-wise attendance (%)")
            heat_df = (processed_df.set_index("Student_Name")[SUBJECTS] / share * 100).round(0).rename(columns=SUBJECT_LABELS)
            fig_heat = px.imshow(heat_df, text_auto=True, aspect="auto", color_continuous_scale="RdYlGn",
                                 zmin=0, zmax=100)
            st.plotly_chart(fig_heat, width="stretch")
        with v2:
            st.subheader("Safe vs defaulter")
            fig_pie = px.pie(processed_df, names="Status", color="Status", hole=0.5, color_discrete_map=STATUS_COLORS)
            st.plotly_chart(fig_pie, width="stretch")

    # -------- ML Predictor
    with tab4:
        st.subheader("End-sem score predictor (multiple linear regression)")
        st.markdown(
            f"Trained on 60 senior-batch records (simulated demo data). Tested on 20% unseen records: "
            f"R2 = **{r2_acc*100:.1f}%**, average error about **{mae_acc:.1f} marks**."
        )
        m_left, m_right = st.columns([1, 2])
        with m_left:
            test_att = st.slider("Attendance (%)", 30.0, 100.0, 68.0, 1.0)
            test_int = st.slider("Internal marks (out of 30)", 5, 30, 18, 1)
            pred_score = float(np.clip(ml_model.predict([[test_att, test_int]])[0], 0, 100))
            st.metric("Predicted score", f"{pred_score:.1f} / 100", border=True)
            if pred_score < 50:
                st.error("High academic failure risk")
            elif pred_score < 65:
                st.warning("Moderate. Needs mentoring")
            else:
                st.success("Strong projected standing")
            st.code(
                f"Score = ({ml_model.coef_[0]:.2f} * Attendance) + ({ml_model.coef_[1]:.2f} * Internals) + {ml_model.intercept_:.2f}",
                language="python",
            )
        with m_right:
            fig_ml = px.scatter(processed_df, x="Overall_Pct", y="ML_Predicted_Score", size="Internal_Marks",
                                color="Status", hover_name="Student_Name", color_discrete_map=STATUS_COLORS,
                                labels={"Overall_Pct": "Attendance %", "ML_Predicted_Score": "Predicted score"})
            st.plotly_chart(fig_ml, width="stretch")
        with st.expander("View training dataset (alumni_training_data table)"):
            st.dataframe(alumni_df, width="stretch", hide_index=True)

    # -------- Notices
    with tab5:
        st.subheader("Parent alert and show-cause notice")
        names = defaulters_df["Student_Name"].tolist() if len(defaulters_df) > 0 else processed_df["Student_Name"].tolist()
        sel_name = st.selectbox("Student", names)
        s_row = processed_df[processed_df["Student_Name"] == sel_name].iloc[0]
        need, can_miss = int(s_row["Classes_Needed"]), int(s_row["Safe_Bunks_Left"])
        if s_row["Target_Reachable"] == "No":
            action_line = (f"Only {remaining} classes remain, so the maximum possible attendance is "
                           f"{s_row['Max_Possible_Pct']}%. Please contact the department.")
            directive = (f"With only {remaining} lectures remaining, the maximum attainable attendance is "
                         f"{s_row['Max_Possible_Pct']}%, below the mandatory {min_req_pct}%. You are required to meet the "
                         f"Co-ordinator with a written explanation.")
        elif need > 0:
            action_line = f"They must attend at least {need} of the remaining {remaining} classes to reach {min_req_pct}%."
            directive = (f"You are required to attend at least {need} of the remaining {remaining} lectures to reach "
                         f"the mandatory {min_req_pct}% by the end of the semester. You may miss at most {can_miss}.")
        else:
            action_line = f"The {min_req_pct}% requirement is already met for the semester."
            directive = f"Attendance requirement of {min_req_pct}% is already satisfied. No action required."
        wa_msg = (f"Dear Parent, Official Alert from IMED BCA Dept: Your ward {s_row['Student_Name']} "
                  f"({s_row['Roll_No']}) has {s_row['Overall_Pct']}% attendance so far ({s_row['Status']}). {action_line}")
        st.link_button(f"Send WhatsApp alert to parent ({s_row['Parent_Phone']})",
                       f"https://wa.me/{s_row['Parent_Phone']}?text={quote(wa_msg)}")

        notice_doc = f"""=====================================================================
{UNIVERSITY.upper()}
{INSTITUTE.upper()}
{CLASS_NAME.upper()} - OFFICIAL SHOW-CAUSE NOTICE
Date: {date.today().strftime('%d-%m-%Y')}
=====================================================================
Student Name       : {s_row['Student_Name']} ({s_row['Roll_No']})
Parent Contact     : +{s_row['Parent_Phone']}
Attendance So Far  : {s_row['Overall_Pct']}% ({s_row['Total_Attended']} of {held} lectures held)
Lectures Remaining : {remaining} of {sem_total} in the semester
Attendance Status  : {s_row['Status'].upper()}
Behavior Pattern   : {s_row['Pattern_Flag']} (Subject StdDev: {s_row['Sub_StdDev']})
Weakest Subject    : {s_row['Weakest_Subject']}
ML Projected Score : {s_row['ML_Predicted_Score']}% (Linear Regression)

DIRECTIVE:
{directive}

Sd/-
{SIGNATORY}
====================================================================="""
        st.text_area("Printable notice", notice_doc, height=360)
        st.download_button("Download notice (.txt)", data=notice_doc, file_name=f"Notice_{s_row['Roll_No']}.txt")


if is_admin:
    render_admin()
else:
    render_student(student_roll)
