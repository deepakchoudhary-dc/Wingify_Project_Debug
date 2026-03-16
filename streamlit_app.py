import os
import time
import uuid
from pathlib import Path

import streamlit as st
from PIL import Image

# Import core functionalities
from main import run_crew, save_analysis_result
from database import get_all_results, init_db

# Ensure DB is initialized
init_db()

# Configure page
st.set_page_config(
    page_title="Financial Document Analyzer - God Mode",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS for Jaw-Dropping UI ---
st.markdown("""
<style>
    /* Global Styling */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Hero Title */
    .hero-title {
        font-size: 3.5rem;
        font-weight: 800;
        background: -webkit-linear-gradient(45deg, #00f2fe, #4facfe, #00f2fe);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0px;
        padding-bottom: 10px;
    }
    
    .hero-subtitle {
        font-size: 1.25rem;
        font-weight: 300;
        color: #A0AEC0;
        margin-bottom: 2rem;
    }

    /* Container Styling */
    .glass-container {
        background: rgba(255, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        -webkit-backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
    }
    
    /* Hide Streamlit Branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Uploader tweaking */
    [data-testid="stFileUploader"] {
        padding: 2rem;
        border: 2px dashed #4facfe;
        border-radius: 15px;
        background-color: rgba(79, 172, 254, 0.05);
        transition: all 0.3s ease;
    }
    [data-testid="stFileUploader"]:hover {
        border-color: #00f2fe;
        background-color: rgba(79, 172, 254, 0.1);
    }

    /* Buttons */
    .stButton>button {
        background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%);
        color: #1a1a2e;
        border: none;
        border-radius: 8px;
        padding: 0.75rem 2rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        transition: all 0.3s ease;
        width: 100%;
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 20px -10px rgba(0, 242, 254, 0.5);
        color: #1a1a2e;
    }
</style>
""", unsafe_allow_html=True)

# Application state
if "analysis_started" not in st.session_state:
    st.session_state.analysis_started = False
if "analysis_complete" not in st.session_state:
    st.session_state.analysis_complete = False
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = ""

# --- Sidebar: History ---
with st.sidebar:
    st.markdown("### 📚 Analysis History")
    st.markdown("Browse previous local analyses.")
    st.divider()
    
    # Fetch results (limiting to 10 latest)
    try:
        history = get_all_results(limit=10)
        if not history:
            st.info("No prior analyses found.")
        else:
            for item in history:
                with st.expander(f"📄 {item['filename']} \n({item['created_at'][:10]})"):
                    st.caption(f"**Query:** {item['query']}")
                    if st.button("Load Report", key=f"btn_{item['analysis_id']}"):
                        st.session_state.analysis_result = item['result']
                        st.session_state.analysis_complete = True
                        st.session_state.analysis_started = True
    except Exception as e:
        st.error("Failed to load DB history.")

# --- Main Hero Area ---
st.markdown('<div class="hero-title">Nexus AI Analyzer</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-subtitle">Fully Local, Privacy-First Financial Intelligence. Powered by Ollama + CrewAI.</div>', unsafe_allow_html=True)

# Only show upload if not analyzing OR if we want to do a new one
if not st.session_state.analysis_started or st.session_state.analysis_complete:
    
    with st.container():
        st.markdown('<div class="glass-container">', unsafe_allow_html=True)
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.markdown("### 📤 Upload Financial Document")
            uploaded_file = st.file_uploader("Upload 10-K, 10-Q, or any Investor Report (.pdf)", type="pdf")
            
        with col2:
            st.markdown("### 🎯 Investigation Focus")
            query = st.text_area("What should the agents focus on?", 
                                 value="Analyze this financial document and provide comprehensive investment insights, identifying key risks and growth areas.",
                                 height=110)
        
        if uploaded_file is not None:
            if st.button("🚀 Launch Autonomous Agents"):
                st.session_state.analysis_started = True
                st.session_state.analysis_complete = False
                
                # Save file locally
                DATA_DIR = Path("data")
                DATA_DIR.mkdir(exist_ok=True, parents=True)
                file_id = str(uuid.uuid4())
                file_path = DATA_DIR / f"streamlit_{file_id}.pdf"
                
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                    
                st.session_state.current_file_path = str(file_path)
                st.session_state.current_file_name = uploaded_file.name
                st.session_state.current_query = query
                st.session_state.current_file_id = file_id
                
                st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

# --- Analysis Execution Area ---
if st.session_state.analysis_started and not st.session_state.analysis_complete:
    st.markdown("### 🤖 Agents at Work...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # Simulate setup UI
    steps = [
        "Waking up local Ollama Model (qwen3:1.7b)...",
        "Deploying Financial Document Verification Specialist...",
        "Scanning PDF content and structures...",
        "Extracting key metrics for the Senior Financial Analyst...",
        "Running risk models via the Risk Assessment Specialist...",
        "Synthesizing final investment guidance..."
    ]
    
    # We execute run_crew synchronously since this is a local app
    # To keep UI slightly responsive we could thread it, but for an immediate stunning effect
    # we'll run it in a spinner.
    with st.spinner("Executing Local Multi-Agent Pipeline... (This may take a few minutes depending on your hardware)"):
        start_time = time.time()
        try:
            result_text = run_crew(
                query=st.session_state.current_query,
                file_path=st.session_state.current_file_path
            )
            
            # Save to DB
            save_analysis_result(
                analysis_id=st.session_state.current_file_id,
                filename=st.session_state.current_file_name,
                query=st.session_state.current_query,
                result=result_text,
                user_id=None # Anonymous local usage
            )
            
            st.session_state.analysis_result = result_text
            st.session_state.analysis_complete = True
            
        except Exception as e:
            st.error(f"Pipeline encountered a critical failure: {str(e)}")
            st.session_state.analysis_started = False
            
    # Clean up file
    try:
        os.remove(st.session_state.current_file_path)
    except:
        pass
        
    st.rerun()

# --- Results Presentation ---
if st.session_state.analysis_complete:
    st.balloons()
    
    st.markdown("### 🏆 Comprehensive Financial Intelligence Report")
    
    st.markdown('<div class="glass-container">', unsafe_allow_html=True)
    # The result from crewAI is usually markdown. We render it directly.
    st.markdown(st.session_state.analysis_result, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        if st.button("New Analysis"):
            st.session_state.analysis_started = False
            st.session_state.analysis_complete = False
            st.session_state.analysis_result = ""
            st.rerun()
