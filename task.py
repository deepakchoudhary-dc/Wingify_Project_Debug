"""
Financial Document Analyzer - Task Factory

Creates fresh CrewAI Task objects for each analysis request to avoid
cross-request task-state leakage under concurrent load.
"""

from crewai import Task
from tools import (
    search_tool,
    read_financial_document,
    analyze_investment_data,
    assess_risk_factors,
)


def build_financial_tasks(verifier, financial_analyst, investment_advisor, risk_assessor):
    """Return a new list of pipeline tasks for one crew execution."""
    document_verification_task = Task(
        description=(
            "Verify the financial document located at '{file_path}'.\n"
            "1. Read the document using the 'Read Financial Document' tool with the exact file_path '{file_path}'.\n"
            "2. Confirm whether it is a legitimate financial document "
            "(e.g., 10-Q, 10-K, annual report, earnings release, financial statement).\n"
            "3. Identify the company name, reporting period, and document type.\n"
            "4. Check for data integrity - look for missing sections, garbled text, or anomalies.\n"
            "5. Provide a clear VERIFIED or FLAGGED status with reasoning.\n"
            "6. Include a compact 'Financial Data Snapshot' with only the most material figures "
            "(max 8 bullet points) so downstream tasks have concrete numeric context."
        ),
        expected_output=(
            "A structured verification report:\n"
            "1. Document Type\n"
            "2. Company Name\n"
            "3. Reporting Period\n"
            "4. Verification Status (VERIFIED or FLAGGED)\n"
            "5. Data Quality Notes\n"
            "6. Financial Data Snapshot (key figures/tables)\n"
            "7. Summary"
        ),
        agent=verifier,
        tools=[read_financial_document],
        async_execution=False,
    )

    financial_analysis_task = Task(
        description=(
            "Perform a comprehensive financial analysis to address the user's query: {query}\n\n"
            "Use context from the verification task and stay grounded in document data.\n"
            "1. Extract key metrics: revenue, net income, margins, EPS, free cash flow, debt, equity.\n"
            "2. Identify QoQ/YoY trends where available.\n"
            "3. Highlight the most significant financial developments.\n"
            "4. Use web search only when a specific market comparison is essential, and at most one query.\n"
            "5. Do not fabricate numbers.\n"
            "6. Keep output concise and decision-focused."
        ),
        expected_output=(
            "A comprehensive financial analysis report:\n"
            "1. Executive Summary\n"
            "2. Key Financial Metrics (actual values)\n"
            "3. Trend Analysis\n"
            "4. Segment/Business Unit Breakdown (if available)\n"
            "5. Notable Items\n"
            "6. Conclusion"
        ),
        agent=financial_analyst,
        tools=[search_tool],
        context=[document_verification_task],
        async_execution=False,
    )

    investment_analysis_task = Task(
        description=(
            "Based on prior task outputs, provide investment insights for the query: {query}\n\n"
            "1. Evaluate investment potential from financial health, growth trajectory, and valuation.\n"
            "2. Use 'Analyze Investment Data' to cross-check key metrics.\n"
            "3. Use web search only when a specific peer/market data point is required, and at most one query.\n"
            "4. Provide recommendations for conservative, moderate, and aggressive profiles.\n"
            "5. Ground recommendations in document-derived data.\n"
            "6. Include proper disclaimers and explicit assumptions."
        ),
        expected_output=(
            "A structured investment analysis report:\n"
            "1. Investment Thesis\n"
            "2. Valuation Assessment\n"
            "3. Recommendations by Investor Profile\n"
            "4. Key Catalysts\n"
            "5. Key Risks\n"
            "6. Disclaimer"
        ),
        agent=investment_advisor,
        tools=[analyze_investment_data, search_tool],
        context=[document_verification_task, financial_analysis_task],
        async_execution=False,
    )

    risk_assessment_task = Task(
        description=(
            "Conduct a comprehensive risk assessment in context of: {query}\n\n"
            "1. Use the document context from previous tasks.\n"
            "2. Pass context text (not file path) to 'Assess Risk Factors'.\n"
            "3. Categorize risks: market, credit, operational, regulatory, financial, competitive, macro.\n"
            "4. Rate each category: Low / Medium / High / Critical with justification.\n"
            "5. Recommend actionable mitigation strategies.\n"
            "6. Provide an overall risk rating grounded in document evidence.\n"
            "7. Keep findings concise and avoid repeating previous sections."
        ),
        expected_output=(
            "A detailed risk assessment report:\n"
            "1. Risk Summary Table: Category | Rating | Key Factors\n"
            "2. Market and Industry Risks\n"
            "3. Company-Specific Risks\n"
            "4. Risk Mitigation Recommendations\n"
            "5. Overall Risk Rating\n"
            "6. Monitoring Indicators"
        ),
        agent=risk_assessor,
        tools=[assess_risk_factors],
        context=[document_verification_task, financial_analysis_task, investment_analysis_task],
        async_execution=False,
    )

    return [
        document_verification_task,
        financial_analysis_task,
        investment_analysis_task,
        risk_assessment_task,
    ]
