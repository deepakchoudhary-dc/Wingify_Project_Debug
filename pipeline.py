"""
Financial Document Analyzer - Centralized Pipeline Runner.

Combines the CrewAI execution flow, aggregates outputs from all agents
into a structured JSON payload, and provides formatting helpers.
"""

import json
import logging
from crewai import Crew, Process
from agents import build_agents
from task import build_financial_tasks

logger = logging.getLogger(__name__)


def run_financial_pipeline(query: str, file_path: str) -> str:
    """
    Executes the multi-agent financial analysis crew sequentially.
    Collects outputs from all tasks and bundles them into a structured JSON string.
    """
    logger.info("Initializing fresh agent and task instances for Crew pipeline execution.")
    verifier, financial_analyst, investment_advisor, risk_assessor = build_agents()
    tasks = build_financial_tasks(verifier, financial_analyst, investment_advisor, risk_assessor)
    
    financial_crew = Crew(
        agents=[verifier, financial_analyst, investment_advisor, risk_assessor],
        tasks=tasks,
        process=Process.sequential,
        verbose=False,
    )
    
    logger.info("Starting Crew pipeline kickoff.")
    crew_output = financial_crew.kickoff(inputs={"query": query, "file_path": file_path})
    
    # Extract the individual task outputs. CrewOutput contains a tasks_output list.
    tasks_output = crew_output.tasks_output
    
    output_dict = {
        "verification": tasks_output[0].raw if len(tasks_output) > 0 else "",
        "financial_analysis": tasks_output[1].raw if len(tasks_output) > 1 else "",
        "investment_insights": tasks_output[2].raw if len(tasks_output) > 2 else "",
        "risk_assessment": tasks_output[3].raw if len(tasks_output) > 3 else ""
    }
    
    # Check for critical errors returned in tool executions
    for name, content in output_dict.items():
        if "TOOL_ERROR:" in content:
            raise RuntimeError(f"Analysis pipeline encountered tool failure in task '{name}': {content}")
            
    return json.dumps(output_dict)


def format_json_to_markdown(json_str: str) -> str:
    """
    Converts a structured JSON output back to a beautiful, unified Markdown report
    suitable for file artifacts or plain text displays.
    """
    try:
        data = json.loads(json_str)
        report = []
        
        if "verification" in data and data["verification"]:
            report.append("# 1. Document Verification Report\n")
            report.append(data["verification"].strip())
            report.append("\n" + "="*80 + "\n")
            
        if "financial_analysis" in data and data["financial_analysis"]:
            report.append("# 2. Financial Analysis Report\n")
            report.append(data["financial_analysis"].strip())
            report.append("\n" + "="*80 + "\n")
            
        if "investment_insights" in data and data["investment_insights"]:
            report.append("# 3. Investment Insights & Advisory\n")
            report.append(data["investment_insights"].strip())
            report.append("\n" + "="*80 + "\n")
            
        if "risk_assessment" in data and data["risk_assessment"]:
            report.append("# 4. Financial Risk Assessment\n")
            report.append(data["risk_assessment"].strip())
            report.append("\n")
            
        return "\n".join(report).strip()
    except Exception:
        # If the input isn't valid JSON, return it raw
        return json_str
