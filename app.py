from datetime import date, timedelta
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Student Attendance", layout="wide")


def get_supabase():
    if "supabase" not in st.session_state:
        st.session_state["supabase"] = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"]
        )
    return st.session_state["supabase"]


supabase = get_supabase()

# ==========================================
# LOGIN GATE
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
            login_btn = st.form_submit_button(
                "Sign In", type="primary", use_container_width=True
            )

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
# CHECK ROLE & FETCH ALLOWED CLASSES
# ==========================================
user_email = st.session_state["user"].email.lower()
admin_rows = (
    supabase.table("admins").select("email").eq("email", user_email).execute().data
)
is_admin = len(admin_rows) > 0

# RLS automatically returns all classes for admin, or only assigned classes for lecturers
class_rows = (
    supabase.table("classes").select("*").order("class_name").execute().data
)
allowed_classes = [c["class_name"] for c in class_rows]

# RLS automatically returns only students in allowed classes
students = (
    supabase.table("students").select("*").order("full_name").execute().data
)

st.title("Student Attendance Platform")

# --- Sidebar: Account & Add Student ---
with st.sidebar:
    role_label = "Admin" if is_admin else "Lecturer"
    st.caption(f"Signed in as: **{user_email}** ({role_label})")
    if st.button("Sign Out", use_container_width=True):
        supabase.auth.sign_out()
        st.session_state["user"] = None
        del st.session_state["supabase"]
        st.rerun()

    st.divider()
    st.header("Add Student")

    if not allowed_classes:
        if is_admin:
            st.info("Create a class in the Manage Classes tab first.")
        else:
            st.info("No classes assigned to you yet. Ask the admin to assign your classes.")
    else:
        with st.form("add_student_form", clear_on_submit=True):
            student_id = st.text_input("Student ID (e.g. STU004)")
            full_name = st.text_input("Full Name")
            class_name = st.selectbox("Class", allowed_classes)
            add_btn = st.form_submit_button("Add Student")

            if add_btn:
                if student_id and full_name:
                    try:
                        supabase.table("students").insert(
                            {
                                "student_id": student_id.strip(),
                                "full_name": full_name.strip(),
                                "class_name": class_name,
                            }
                        ).execute()
                        st.success(f"Added {full_name} to {class_name}!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not add student: {e}")
                else:
                    st.warning("Please enter both Student ID and Full Name.")

# --- Build Tabs (Admin gets a 4th tab to manage classes) ---
tab_names = ["Mark Attendance", "Weekly Register & Export", "Full Raw Log"]
if is_admin:
    tab_names.append("Manage Classes (Admin)")

tabs = st.tabs(tab_names)
tab_mark, tab_weekly, tab_log = tabs[0], tabs[1], tabs[2]

# ==========================================
# TAB 1: MARK ATTENDANCE
# ==========================================
with tab_mark:
    if not allowed_classes:
        st.info("No classes available yet.")
    elif not students:
        st.info("No students in your classes yet. Add one using the sidebar.")
    else:
        col1, col2 = st.columns(2)
        selected_class = col1.selectbox("Select Class", allowed_classes, key="mark_class")
        selected_date = col2.date_input("Date", value=date.today(), key="mark_date")

        class_students = [s for s in students if s["class_name"] == selected_class]

        if not class_students:
            st.info(f"No students in {selected_class} yet. Add them in the sidebar.")
        else:
            existing_rows = (
                supabase.table("attendance")
                .select("student_id, status")
                .eq("attendance_date", str(selected_date))
                .execute()
                .data
            )
            existing_map = {r["student_id"]: r["status"] for r in existing_rows}

            if any(s["student_id"] in existing_map for s in class_students):
                st.caption(
                    "Showing previously saved attendance for this date — edit and save to update."
                )

            with st.form("attendance_form"):
                st.subheader(f"Roll Call — {selected_class} ({selected_date})")
                statuses = {}
                options = ["Present", "Absent", "Late"]

                for student in class_students:
                    sid = student["student_id"]
                    label = f"{sid} — {student['full_name']}"
                    saved_status = existing_map.get(sid, "Present")
                    default_idx = (
                        options.index(saved_status) if saved_status in options else 0
                    )

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
                    st.success(
                        f"Saved attendance for {len(records)} students on {selected_date}!"
                    )

# ==========================================
# TAB 2: WEEKLY DAY-BY-DAY REGISTER & EXPORT
# ==========================================
with tab_weekly:
    if not allowed_classes or not students:
        st.info("No students available to display yet.")
    else:
        col1, col2, col3 = st.columns([2, 2, 1])

        class_filter_options = (
            ["All"] + allowed_classes if len(allowed_classes) > 1 else allowed_classes
        )
        weekly_class = col1.selectbox("Class", class_filter_options, key="weekly_class")
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

        log_class_options = (
            ["All"] + sorted(df["Class"].unique())
            if len(df["Class"].unique()) > 1
            else sorted(df["Class"].unique())
        )
        filter_class = st.selectbox("Filter by Class", log_class_options, key="log_class")
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

# ==========================================
# TAB 4: MANAGE CLASSES (ADMIN ONLY)
# ==========================================
if is_admin:
    with tabs[3]:
        st.subheader("Create or Reassign a Class")
        with st.form("manage_class_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            new_class_name = c1.text_input("Class Name (e.g. DCS 111)")
            assigned_email = c2.text_input("Lecturer Email (e.g. lecturer1@school.edu)")
            save_class_btn = st.form_submit_button("Save Class Assignment", type="primary")

            if save_class_btn:
                if new_class_name and assigned_email:
                    try:
                        supabase.table("classes").upsert(
                            {
                                "class_name": new_class_name.strip(),
                                "lecturer_email": assigned_email.strip().lower(),
                            },
                            on_conflict="class_name",
                        ).execute()
                        st.success(
                            f"Assigned {new_class_name.strip()} to {assigned_email.strip().lower()}!"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not save class: {e}")
                else:
                    st.warning("Please enter both a class name and a lecturer email.")

        st.subheader("Current Class Assignments")
        if class_rows:
            classes_df = pd.DataFrame(class_rows).rename(
                columns={"class_name": "Class", "lecturer_email": "Assigned Lecturer"}
            )
            st.dataframe(classes_df, use_container_width=True, hide_index=True)
        else:
            st.info("No classes created yet.")
