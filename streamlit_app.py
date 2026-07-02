import os
import time
import json
import tempfile
import requests
import streamlit as st
import pandas as pd

# ── Page Configuration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI Financial Terminal",
    layout="wide",
    page_icon="🏦",
    initial_sidebar_state="expanded"
)

# Custom premium styling for Bloomberg-like dark theme aesthetics
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Outfit', sans-serif;
    }
    
    .metric-card {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 20px;
        border-radius: 12px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        background: rgba(255, 255, 255, 0.08);
    }
    .metric-val {
        font-size: 28px;
        font-weight: 700;
        margin: 5px 0;
        background: linear-gradient(45deg, #00C9FF, #92FE9D);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .metric-label {
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 1px;
        color: #8892b0;
    }
    
    .status-badge {
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 12px;
        display: inline-block;
    }
    .status-completed { background: rgba(46, 204, 113, 0.15); color: #2ecc71; border: 1px solid #2ecc71; }
    .status-processing { background: rgba(241, 196, 15, 0.15); color: #f1c40f; border: 1px solid #f1c40f; }
    .status-pending { background: rgba(52, 152, 219, 0.15); color: #3498db; border: 1px solid #3498db; }
    .status-failed { background: rgba(231, 76, 60, 0.15); color: #e74c3c; border: 1px solid #e74c3c; }
    
    .risk-badge {
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: bold;
        font-size: 11px;
    }
    .risk-low { background: #2ecc71; color: white; }
    .risk-medium { background: #f1c40f; color: black; }
    .risk-high { background: #e67e22; color: white; }
    .risk-critical { background: #e74c3c; color: white; }

    .advisory-card {
        padding: 15px;
        border-radius: 8px;
        border-left: 5px solid;
        margin-bottom: 15px;
    }
</style>
""", unsafe_allow_html=True)

# ── API Settings ─────────────────────────────────────────────────────────────
API_URL = st.sidebar.text_input("FastAPI Service URL", value="http://localhost:8000")

# ── Session State Management ──────────────────────────────────────────────────
if "api_key" not in st.session_state:
    st.session_state["api_key"] = ""
if "username" not in st.session_state:
    st.session_state["username"] = ""
if "selected_analysis_id" not in st.session_state:
    st.session_state["selected_analysis_id"] = None
if "current_result" not in st.session_state:
    st.session_state["current_result"] = None

# Helper to check headers
def get_headers():
    headers = {}
    if st.session_state["api_key"]:
        headers["X-API-Key"] = st.session_state["api_key"]
    return headers

# ── Sidebar & Authentication ──────────────────────────────────────────────────
st.sidebar.title("🏦 Financial Terminal Control")

# Simple, non-blocking Key Management & Registration
with st.sidebar.expander("🔑 API Credentials / Registration", expanded=not bool(st.session_state["api_key"])):
    st.markdown("Authenticate to query documents and persist analysis logs.")
    existing_key = st.text_input("Enter Existing API Key", value=st.session_state["api_key"], type="password")
    if existing_key:
        st.session_state["api_key"] = existing_key
        
    st.divider()
    st.markdown("**Register New User Account**")
    reg_username = st.text_input("Username")
    reg_email = st.text_input("Email (Optional)")
    if st.button("Generate API Key"):
        if reg_username.strip():
            try:
                response = requests.post(f"{API_URL}/users", data={"username": reg_username, "email": reg_email})
                if response.status_code == 201:
                    user_data = response.json().get("user", {})
                    generated_key = user_data.get("api_key")
                    st.session_state["api_key"] = generated_key
                    st.session_state["username"] = user_data.get("username")
                    st.success(f"Account Created! Copy key: {generated_key}")
                    st.rerun()
                else:
                    st.error(response.json().get("detail", "Registration failed"))
            except Exception as e:
                st.error(f"Cannot connect to API: {e}")
        else:
            st.warning("Please enter a username.")

# Load past results list if key is set
history_list = []
if st.session_state["api_key"]:
    try:
        hist_response = requests.get(f"{API_URL}/results?limit=50", headers=get_headers())
        if hist_response.status_code == 200:
            history_list = hist_response.json().get("results", [])
    except Exception:
        pass

# History dropdown in sidebar
if history_list:
    st.sidebar.divider()
    st.sidebar.subheader("🗂️ Previous Analyses")
    
    # Form list options
    options = []
    id_map = {}
    for item in history_list:
        label = f"{item['filename']} ({item['created_at'][:10]})"
        options.append(label)
        id_map[label] = item['analysis_id']
        
    selected_option = st.sidebar.selectbox("Load Result", ["-- Choose a past analysis --"] + options)
    if selected_option != "-- Choose a past analysis --":
        selected_id = id_map[selected_option]
        if st.session_state["selected_analysis_id"] != selected_id:
            st.session_state["selected_analysis_id"] = selected_id
            try:
                res = requests.get(f"{API_URL}/results/{selected_id}", headers=get_headers())
                if res.status_code == 200:
                    st.session_state["current_result"] = res.json().get("result")
                    st.rerun()
            except Exception as e:
                st.sidebar.error(f"Error loading: {e}")

# ── Main Application Interface ────────────────────────────────────────────────
st.title("🏦 AI Financial Document Analyzer")
st.markdown("Upload complex financial reports (10-K, 10-Q, annual reports) to evaluate metrics, extract insights, and assess risk profiles.")

tab_run, tab_view = st.tabs(["🚀 Run New Analysis", "📊 Dashboard View"])

with tab_run:
    # Key status notification
    if not st.session_state["api_key"]:
        st.info("💡 Tip: Enter or generate an API Key in the sidebar to save and view past reports.")

    col_cfg1, col_cfg2 = st.columns([2, 1])
    with col_cfg1:
        query = st.text_area(
            "Analysis Query / Directives", 
            value="Analyze this financial document and provide comprehensive investment insights",
            height=100
        )
    with col_cfg2:
        uploaded_file = st.file_uploader("Upload Financial Document (PDF only)", type=["pdf"])
        st.caption("Maximum upload size: 50MB")

    if st.button("Kickoff Pipeline", type="primary"):
        if not uploaded_file:
            st.error("Please upload a PDF document.")
        elif not st.session_state["api_key"]:
            st.error("An API Key is required to authorize the pipeline execution. Generate one in the sidebar.")
        else:
            with st.status("Initializing asynchronous pipeline runner...", expanded=True) as status_box:
                try:
                    # Upload and run async
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(uploaded_file.getvalue())
                        tmp_path = tmp.name

                    # Prepare files and data
                    files = {"file": (uploaded_file.name, open(tmp_path, "rb"), "application/pdf")}
                    data = {"query": query}
                    
                    status_box.update(label="Dispatching task to backend Celery workers...", state="running")
                    response = requests.post(f"{API_URL}/analyze/async", files=files, data=data, headers=get_headers())
                    
                    # Cleanup local temp file
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                        
                    if response.status_code == 202:
                        analysis_id = response.json().get("analysis_id")
                        dispatched_via = response.json().get("dispatched_via")
                        
                        # Enter polling loop
                        status_box.update(label=f"Task accepted ({dispatched_via}). Monitoring pipeline execution...", state="running")
                        
                        max_checks = 120  # up to 6 minutes
                        success = False
                        
                        for check in range(max_checks):
                            time.sleep(3)
                            chk_res = requests.get(f"{API_URL}/results/{analysis_id}", headers=get_headers())
                            
                            if chk_res.status_code == 200:
                                record = chk_res.json().get("result", {})
                                task_status = record.get("status")
                                
                                if task_status == "completed":
                                    st.session_state["current_result"] = record
                                    st.session_state["selected_analysis_id"] = analysis_id
                                    success = True
                                    status_box.update(label="Analysis completed! Loading dashboard...", state="complete")
                                    time.sleep(1)
                                    st.rerun()
                                    break
                                elif task_status == "failed":
                                    status_box.update(label="Analysis pipeline failed on the backend.", state="error")
                                    st.error(record.get("result", "Unknown error occurred."))
                                    break
                                elif task_status == "processing":
                                    status_box.update(label=f"Pipeline Processing (Step {check//10 + 1}): Running agents...", state="running")
                                elif task_status == "retrying":
                                    status_box.update(label="Back-off threshold reached; retrying task...", state="running")
                            else:
                                status_box.update(label=f"Error checking status: HTTP {chk_res.status_code}", state="running")
                                
                        if not success:
                            st.warning("Pipeline is taking longer than expected. You can check the dashboard later by selecting it in the history sidebar.")
                    else:
                        st.error(f"API Dispatch Error ({response.status_code}): {response.json().get('detail', 'Unknown error')}")
                except Exception as e:
                    status_box.update(label="Network Connection Refused.", state="error")
                    st.error(f"Cannot connect to backend: {e}")

# ── Dashboard Rendering ────────────────────────────────────────────────────────
with tab_view:
    res = st.session_state["current_result"]
    if not res:
        st.info("No analysis active. Run an analysis or select a past report from the sidebar.")
    else:
        # Title metadata card
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            st.markdown(f'<div class="metric-card"><div class="metric-label">Company / Report</div><div class="metric-val" style="font-size: 20px;">{res.get("filename")}</div></div>', unsafe_allow_html=True)
        with col_m2:
            st.markdown(f'<div class="metric-card"><div class="metric-label">Status</div><div style="margin-top:10px;"><span class="status-badge status-{res.get("status")}">{res.get("status").upper()}</span></div></div>', unsafe_allow_html=True)
        with col_m3:
            # Query display
            st.markdown(f'<div class="metric-card"><div class="metric-label">Query Prompt</div><div style="font-size:12px; margin-top:5px; height: 35px; overflow-y:auto; color:#ccc;">{res.get("query")}</div></div>', unsafe_allow_html=True)
        with col_m4:
            # Date display
            st.markdown(f'<div class="metric-card"><div class="metric-label">Analyzed On</div><div class="metric-val" style="font-size: 20px;">{res.get("created_at")[:10]}</div></div>', unsafe_allow_html=True)

        st.divider()

        # Parse structured JSON vs legacy Markdown
        raw_result = res.get("result", "")
        is_json = False
        parsed_data = {}
        
        try:
            parsed_data = json.loads(raw_result)
            if isinstance(parsed_data, dict) and "verification" in parsed_data:
                is_json = True
        except Exception:
            pass

        if is_json:
            # Setup structured views
            d_tabs = st.tabs([
                "🔍 Verification & Snapshot", 
                "📊 Financial Analysis", 
                "💡 Investment Thesis", 
                "⚠️ Risk Matrix",
                "📝 Complete Report"
            ])
            
            # --- Tab 1: Verification ---
            with d_tabs[0]:
                st.markdown("### Document Verification Details")
                st.markdown(parsed_data.get("verification", "No verification output found."))
                
            # --- Tab 2: Financial Analysis ---
            with d_tabs[1]:
                st.markdown("### Deep Financial Metrics & Fundamentals")
                st.markdown(parsed_data.get("financial_analysis", "No financial analysis found."))
                
            # --- Tab 3: Investment Guidance ---
            with d_tabs[2]:
                st.markdown("### Investment Advisory & Allocation Profiles")
                # Highlight recommendations dynamically if structured tags are present
                guidance_text = parsed_data.get("investment_insights", "No investment insights found.")
                st.markdown(guidance_text)
                
            # --- Tab 4: Risk Matrix ---
            with d_tabs[3]:
                st.markdown("### Structured Risk Assessment")
                risk_text = parsed_data.get("risk_assessment", "")
                
                # Check for standard risk lines
                st.markdown(risk_text)
                
            # --- Tab 5: Complete Report ---
            with d_tabs[4]:
                st.markdown("### Combined Analysis Report")
                
                # Compile Markdown
                report = []
                report.append(f"# Analysis Report: {res.get('filename')}\n")
                report.append(f"**Query**: {res.get('query')}\n")
                report.append(f"**Date**: {res.get('created_at')}\n")
                report.append("\n" + "="*80 + "\n")
                
                if parsed_data.get("verification"):
                    report.append("## 1. Verification Report\n" + parsed_data.get("verification"))
                if parsed_data.get("financial_analysis"):
                    report.append("## 2. Financial Analysis\n" + parsed_data.get("financial_analysis"))
                if parsed_data.get("investment_insights"):
                    report.append("## 3. Investment Advisory\n" + parsed_data.get("investment_insights"))
                if parsed_data.get("risk_assessment"):
                    report.append("## 4. Risk Assessment\n" + parsed_data.get("risk_assessment"))
                    
                full_md = "\n\n".join(report)
                
                st.text_area("Copy Markdown", value=full_md, height=400)
                st.download_button(
                    label="Download Markdown Report",
                    data=full_md,
                    file_name=f"financial_report_{res.get('analysis_id')[:8]}.md",
                    mime="text/markdown"
                )

        else:
            # Fallback for legacy plain text results
            st.markdown("### 📄 Narrative Report")
            st.markdown(raw_result)
            
            st.download_button(
                label="Download Report",
                data=raw_result,
                file_name=f"report_{res.get('analysis_id')[:8]}.txt",
                mime="text/plain"
            )
