from datetime import date, timedelta
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Student Attendance", layout="wide")


def get_supabase():
    # Per-user session client so logins are never shared across visitors
    if "supabase" not in st.session_state:
        st.session_state["supabase"] = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        )
    return st.session_state["supabase"]


supabase = get_supabase()

# ==========================================
# LOGIN GATE (Blocks everything until signed in)
# ==========================================
if "user" not in st.session_state:
    st.session_state["user"] = None

if st.session_state["user"] is None:
    st.title("Student Attendance Platform")
    st.caption("Authorized staff only. Please sign in to continue.")

    col_l, col_mid, col_r = st.columns([1, 2, 1])
    with col_mid:
        with st.form("login_form"):
            email = st.text_input("Staff Email")
            password = st.text_input("Password", type="password")
            login_btn = st.form_submit_button("Sign In", type="primary", use_container_width=True)

            if login_btn:
                if email and password:
                    try:
                        res = supabase.auth.sign_in_with_password(
                            {"email": email.strip(), "password": password}
                        )
                        st.session_state["user"] = res.user
                        st.rerun()
                    except Exception:
                        st.error("Invalid email or password.")
                else:
                    st.warning("Please enter both email and password.")
    st.stop()

# ==========================================
# AUTHENTICATED APP (Only runs after sign-in)
# ==========================================
st.title("Student Attendance Platform")

# --- Sidebar: Account & Add Student ---
with st.sidebar:
    st.caption(f"Signed in as: **{st.session_state['user'].email}**")
    if st.button("Sign Out", use_container_width=True):
        supabase.auth.sign_out()
        st.session_state["user"] = None
        del st.session_state["supabase"]
        st.rerun()

    st.divider()
    st.header("Add Student")
    with st.form("add_student_form", clear_on_submit=True):
        student_id = st.text_input("Student ID (e.g. STU004)")
        full_name = st.text_input("Full Name")
        class_name = st.text_input("Class (e.g. CS 101)")
        add_btn = st.form_submit_button("Add Student")

        if add_btn:
            if student_id and full_name and class_name:
                try:
                    supabase.table("students").insert(
                        {
                            "student_id": student_id.strip(),
                            "full_name": full_name.strip(),
                            "class_name": class_name.strip(),
                        }
                    ).execute()
                    st.success(f"Added {full_name}!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not add student: {e}")
            else:
                st.warning("Please fill in all three fields.")

# --- Fetch all students once ---
students = (
    supabase.table("students")
    .select("*")
    .order("full_name")
    .execute()
    .data
)

# --- Main Tabs ---
tab_mark, tab_weekly, tab_log = st.tabs(
    ["Mark Attendance", "Weekly Register & Export", "Full Raw Log"]
)

# ==========================================
# TAB 1: MARK ATTENDANCE
# ==========================================
with tab_mark:
    if not students:
        st.info("No students yet. Add one using the sidebar.")
    else:
        classes = sorted({s["class_name"] for s in students})
        col1, col2 = st.columns(2)
        selected_class = col1.selectbox("Select Class", classes, key="mark_class")
        selected_date = col2.date_input("Date", value=date.today(), key="mark_date")

        class_students = [s for s in students if s["class_name"] == selected_class]

        existing_rows = (
            supabase.table("attendance")
            .select("student_id, status")
            .eq("attendance_date", str(selected_date))
            .execute()
            .data
        )
        existing_map = {r["student_id"]: r["status"] for r in existing_rows}

        if any(s["student_id"] in existing_map for s in class_students):
            st.caption("Showing previously saved attendance for this date — edit and save to update.")

        with st.form("attendance_form"):
            st.subheader(f"Roll Call — {selected_class} ({selected_date})")
            statuses = {}
            options = ["Present", "Absent", "Late"]

            for student in class_students:
                sid = student["student_id"]
                label = f"{sid} — {student['full_name']}"
                saved_status = existing_map.get(sid, "Present")
                default_idx = options.index(saved_status) if saved_status in options else 0

                statuses[sid] = st.radio(
                    label,
                    options=options,
                    index=default_idx,
                    horizontal=True,
                    key=f"status_{selected_class}_{selected_date}_{sid}",
                )

            submitted = st.form_submit_button("Save Attendance", type="primary")

            if submitted:
                records = [
                    {
                        "student_id": sid,
                        "attendance_date": str(selected_date),
                        "status": status,
                    }
                    for sid, status in statuses.items()
                ]
                supabase.table("attendance").upsert(
                    records, on_conflict="student_id,attendance_date"
                ).execute()
                st.success(f"Saved attendance for {len(records)} students on {selected_date}!")

# ==========================================
# TAB 2: WEEKLY DAY-BY-DAY REGISTER & EXPORT
# ==========================================
with tab_weekly:
    if not students:
        st.info("No students yet. Add one using the sidebar.")
    else:
        classes = sorted({s["class_name"] for s in students})
        col1, col2, col3 = st.columns([2, 2, 1])

        weekly_class = col1.selectbox("Class", ["All"] + classes, key="weekly_class")
        picked_date = col2.date_input(
            "Pick any date in the week", value=date.today(), key="weekly_date"
        )
        include_weekend = col3.checkbox("Include Sat/Sun", value=False)

        week_start = picked_date - timedelta(days=picked_date.weekday())
        num_days = 7 if include_weekend else 5
        week_end = week_start + timedelta(days=num_days - 1)
        week_dates = [week_start + timedelta(days=i) for i in range(num_days)]

        st.subheader(
            f"Weekly Attendance: {week_start.strftime('%d %b %Y')} — {week_end.strftime('%d %b %Y')}"
        )

        week_rows = (
            supabase.table("attendance")
            .select("student_id, attendance_date, status")
            .gte("attendance_date", str(week_start))
            .lte("attendance_date", str(week_end))
            .execute()
            .data
        )
        lookup = {
            (r["student_id"], r["attendance_date"]): r["status"] for r in week_rows
        }

        filtered_students = (
            students
            if weekly_class == "All"
            else [s for s in students if s["class_name"] == weekly_class]
        )

        grid_rows = []
        for s in filtered_students:
            sid = s["student_id"]
            row = {"Student ID": sid, "Name": s["full_name"]}
            if weekly_class == "All":
                row["Class"] = s["class_name"]

            present_count = 0
            late_count = 0
            absent_count = 0

            for d in week_dates:
                col_label = d.strftime("%a %d %b")
                status = lookup.get((sid, str(d)), "—")
                row[col_label] = status
                if status == "Present":
                    present_count += 1
                elif status == "Late":
                    late_count += 1
                elif status == "Absent":
                    absent_count += 1

            marked_days = present_count + late_count + absent_count
            row["Present"] = present_count
            row["Late"] = late_count
            row["Absent"] = absent_count
            row["Rate"] = (
                f"{round((present_count / marked_days) * 100)}%"
                if marked_days > 0
                else "—"
            )
            grid_rows.append(row)

        weekly_df = pd.DataFrame(grid_rows)
        st.dataframe(weekly_df, use_container_width=True, hide_index=True)

        safe_class = weekly_class.replace(" ", "_")
        csv_name = f"{safe_class}_week_{week_start}_to_{week_end}.csv"
        weekly_csv = weekly_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download Weekly CSV",
            data=weekly_csv,
            file_name=csv_name,
            mime="text/csv",
            type="primary",
        )

# ==========================================
# TAB 3: FULL RAW LOG
# ==========================================
with tab_log:
    rows = (
        supabase.table("attendance")
        .select("attendance_date, status, students(student_id, full_name, class_name)")
        .order("attendance_date", desc=True)
        .execute()
        .data
    )

    if not rows:
        st.info("No attendance records saved yet.")
    else:
        flat_rows = [
            {
                "Date": r["attendance_date"],
                "Class": r["students"]["class_name"],
                "Student ID": r["students"]["student_id"],
                "Name": r["students"]["full_name"],
                "Status": r["status"],
            }
            for r in rows
            if r.get("students")
        ]
        df = pd.DataFrame(flat_rows)

        filter_class = st.selectbox(
            "Filter by Class", ["All"] + sorted(df["Class"].unique()), key="log_class"
        )
        if filter_class != "All":
            df = df[df["Class"] == filter_class]

        st.dataframe(df, use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download Full Log CSV",
            data=csv,
            file_name="attendance_full_log.csv",
            mime="text/csv",
        )
