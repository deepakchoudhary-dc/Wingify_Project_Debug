import os
import tempfile
import streamlit as st

from crewai import Crew, Process
from agents import build_agents
from task import build_financial_tasks
from database import init_db

# Initialize database
init_db()

st.set_page_config(page_title="AI Financial Document Analyzer", layout="wide", page_icon="📊")

st.title("📊 AI Financial Document Analyzer")
st.markdown("Upload a financial PDF and let our CrewAI multi-agent system analyze it. This tool reads the document, extracts financial metrics, provides investment insights, and assesses risk factors.")

with st.sidebar:
    st.header("🔑 API Configuration")
    st.markdown("Set your API keys (can also be loaded from `.env`).")
    gemini_key = st.text_input("Gemini API Key", value=os.getenv("GEMINI_API_KEY", ""), type="password")
    serper_key = st.text_input("Serper API Key", value=os.getenv("SERPER_API_KEY", ""), type="password")
    
    if gemini_key:
        os.environ["GEMINI_API_KEY"] = gemini_key
    if serper_key:
        os.environ["SERPER_API_KEY"] = serper_key

query = st.text_area("Analysis Query", value="Analyze this financial document and provide comprehensive investment insights")

uploaded_file = st.file_uploader("Upload Financial Document (PDF)", type=["pdf"])

if st.button("Run Analysis", type="primary"):
    if not uploaded_file:
        st.error("Please upload a PDF document first.")
    elif not os.environ.get("GEMINI_API_KEY") and not os.environ.get("OPENAI_API_KEY"):
        st.error("Please provide an API key in the sidebar.")
    else:
        with st.spinner("Agents are analyzing the document... This may take 30-120 seconds depending on the document size."):
            temp_path = None
            try:
                # Save uploaded file safely to a temporary path
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    temp_path = tmp_file.name

                # Build agents and tasks
                verifier, financial_analyst, investment_advisor, risk_assessor = build_agents()
                tasks = build_financial_tasks(verifier, financial_analyst, investment_advisor, risk_assessor)
                
                financial_crew = Crew(
                    agents=[verifier, financial_analyst, investment_advisor, risk_assessor],
                    tasks=tasks,
                    process=Process.sequential,
                    verbose=False,
                )
                
                # Run the pipeline synchronously
                result = financial_crew.kickoff(inputs={"query": query, "file_path": temp_path})
                result_text = str(result)
                
                if "TOOL_ERROR:" in result_text:
                    st.error("Analysis pipeline encountered a tool failure.")
                    st.error(result_text)
                else:
                    st.success("Analysis Complete!")
                    st.markdown("### 📄 Analysis Results")
                    st.markdown(result_text)
                    
            except Exception as e:
                st.error(f"An error occurred during analysis: {str(e)}")
            finally:
                # Cleanup temp file
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
