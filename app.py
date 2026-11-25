from datetime import date
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Student Attendance", layout="wide")
st.title("Student Attendance Platform")


@st.cache_resource
def get_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


supabase = get_supabase()

# --- Sidebar: Add a new student ---
with st.sidebar:
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

# --- Main Tabs ---
tab_mark, tab_view = st.tabs(["Mark Attendance", "View & Export Records"])

students = (
    supabase.table("students")
    .select("*")
    .order("full_name")
    .execute()
    .data
)

with tab_mark:
    if not students:
        st.info("No students yet. Add one using the sidebar.")
    else:
        classes = sorted({s["class_name"] for s in students})
        col1, col2 = st.columns(2)
        selected_class = col1.selectbox("Select Class", classes)
        selected_date = col2.date_input("Date", value=date.today())

        class_students = [s for s in students if s["class_name"] == selected_class]

        with st.form("attendance_form"):
            st.subheader(f"Roll Call — {selected_class} ({selected_date})")
            statuses = {}

            for student in class_students:
                sid = student["student_id"]
                label = f"{sid} — {student['full_name']}"
                statuses[sid] = st.radio(
                    label,
                    options=["Present", "Absent", "Late"],
                    horizontal=True,
                    key=f"status_{sid}",
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
                st.success(f"Saved attendance for {len(records)} students!")

with tab_view:
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

        filter_class = st.selectbox("Filter by Class", ["All"] + sorted(df["Class"].unique()))
        if filter_class != "All":
            df = df[df["Class"] == filter_class]

        st.dataframe(df, use_container_width=True, hide_index=True)

        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download as CSV",
            data=csv,
            file_name="attendance_records.csv",
            mime="text/csv",
        )