import os
import sqlite3
import streamlit as st
from pydantic import BaseModel, Field
from typing import List, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# Check Streamlit Cloud secrets first, then fallback to os.getenv / .envgit add requirements.txt
api_key = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")

if not api_key:
    st.error("Missing GEMINI_API_KEY. Please add it to your Streamlit Cloud Secrets or local .env file.")
    st.stop()

st.set_page_config(page_title="ArchScale AS-02 Engine", layout="wide")

# ----------------- DATABASE SETUP (SQLite) -----------------
DB_FILE = "archscale_project.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            description TEXT,
            assignee TEXT,
            deadline TEXT,
            source_quote TEXT
        )
    """)
    conn.commit()
    return conn

def insert_items(items):
    conn = get_db()
    cursor = conn.cursor()
    for item in items:
        cursor.execute("""
            INSERT INTO project_items (category, description, assignee, deadline, source_quote)
            VALUES (?, ?, ?, ?, ?)
        """, (item.category, item.description, item.assignee or "Unassigned", item.deadline or "TBD", item.source_quote))
    conn.commit()
    conn.close()
def clear_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM project_items")
    conn.commit()
    conn.close()
def query_memory(search_term=""):
    conn = get_db()
    cursor = conn.cursor()
    if search_term:
        cursor.execute("""
            SELECT category, description, assignee, deadline, source_quote 
            FROM project_items 
            WHERE description LIKE ? OR source_quote LIKE ? OR assignee LIKE ?
            ORDER BY id DESC
        """, (f"%{search_term}%", f"%{search_term}%", f"%{search_term}%"))
    else:
        cursor.execute("SELECT category, description, assignee, deadline, source_quote FROM project_items ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows

# ----------------- PYDANTIC EXTRACTION SCHEMA -----------------
class ExtractedItem(BaseModel):
    category: str = Field(description="Must be 'Task', 'Decision', or 'Pending Blocker'")
    description: str = Field(description="Actionable summary of the item")
    assignee: Optional[str] = Field(None, description="Person, trade, or role responsible")
    deadline: Optional[str] = Field(None, description="Extracted date or timeline")
    source_quote: str = Field(description="Exact sentence from the source communication")

class CommunicationReport(BaseModel):
    summary: str = Field(description="2-sentence executive summary")
    stakeholders: List[str] = Field(description="List of detected stakeholders and roles")
    items: List[ExtractedItem] = Field(description="Extracted items")

# ----------------- STREAMLIT FRONTEND -----------------
st.title("🏗️ ArchScale: Intelligent Project Communication Layer")
st.caption("Parses unstructured project dialogue into relational task records and searchable memory.")

default_chat = """[10:14 AM] Site Supervisor: Footing depth on grid 4 is only 1.2m. Soil report says we need 1.8m.
[10:16 AM] Lead Architect: Do not pour concrete yet. Structural team must inspect today.
[10:22 AM] MEP Contractor: If concrete is delayed past Friday, electrical conduits will be held up until Tuesday.
[10:30 AM] Project Manager: Client approved extra excavation cost. Structural team visit scheduled for 3 PM today. Site team to proceed with 1.8m depth excavation immediately."""

user_input = st.text_area("Paste WhatsApp thread, meeting transcript, or site notes:", value=default_chat, height=160)

if st.button("🚀 Process & Store to Database", type="primary"):
    if not api_key:
        st.error("Missing GEMINI_API_KEY in .env file.")
    else:
        with st.spinner("Analyzing communication and persisting records..."):
            client = genai.Client(api_key=api_key)
            prompt = f"""
            Analyze this AEC project communication. Extract tasks, decisions, and blockers.
            Map assignees to trades or roles if exact names are missing.
            
            Text:
            {user_input}
            """
        response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=CommunicationReport,
        temperature=0.1,
    ),
)
        report = CommunicationReport.model_validate_json(response.text)
        insert_items(report.items)
        st.success(f"Extracted and saved {len(report.items)} records to SQLite database!")
        st.info(f"**Summary:** {report.summary}")

# ----------------- PERSISTENT BOARD & SEARCH -----------------
st.divider()
st.subheader("🔍 Searchable Project Memory & Board")

search_term = st.text_input("Query project memory (e.g., 'concrete', 'excavation', 'structural'):", "")
records = query_memory(search_term)

col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### 📌 Action Items")
    for r in [x for x in records if x[0] == "Task"]:
        with st.container(border=True):
            st.write(f"**{r[1]}**")
            st.caption(f"👤 Assignee: **{r[2]}** | 📅 Due: **{r[3]}**")
            st.caption(f"💬 *Source:* \"{r[4]}\"")

with col2:
    st.markdown("### ⚖️ Decisions")
    for r in [x for x in records if x[0] == "Decision"]:
        with st.container(border=True):
            st.write(f"**{r[1]}**")
            st.caption(f"💬 *Source:* \"{r[4]}\"")

with col3:
    st.markdown("### ⚠️ Blockers")
    for r in [x for x in records if x[0] == "Pending Blocker"]:
        with st.container(border=True):
            st.write(f"**{r[1]}**")
            st.caption(f"💬 *Source:* \"{r[4]}\"")
# ----------------- DEMO CONTROLS -----------------
st.divider()
ctrl_col1, ctrl_col2 = st.columns([1, 4])

with ctrl_col1:
    if st.button("🗑️ Reset Database", type="secondary"):
        clear_db()
        st.rerun()

with ctrl_col2:
    if records:
        import pandas as pd

        df = pd.DataFrame(
            records,
            columns=[
                "Category",
                "Description",
                "Assignee",
                "Deadline",
                "Source Quote",
            ],
        )
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Export to CSV (Project Register)",
            data=csv,
            file_name="archscale_project_register.csv",
            mime="text/csv",
        )