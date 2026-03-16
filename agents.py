"""
Financial Document Analyzer - Agent Factory.

Creates CrewAI agents for:
- document verification
- financial analysis
- investment guidance
- risk assessment
"""

import os

from dotenv import load_dotenv
from crewai import Agent, LLM

from tools import (
    search_tool,
    read_financial_document,
    analyze_investment_data,
    assess_risk_factors,
)

load_dotenv()


def _build_llm() -> LLM:
    """Built to rely on local Ollama via the user's explicit request."""
    model_name = os.getenv("MODEL_NAME", "ollama/qwen3:1.7b")
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    # CrewAI (LiteLLM) connects to Ollama automatically when prefixed with ollama/
    return LLM(model=model_name, base_url=base_url)


def build_agents() -> tuple[Agent, Agent, Agent, Agent]:
    """
    Create a fresh set of agents for one crew execution.

    Fresh agent objects reduce shared mutable state across concurrent requests.
    """
    llm = _build_llm()

    verifier = Agent(
        role="Financial Document Verification Specialist",
        goal=(
            "Verify the uploaded document, identify issuer/period/type, and flag "
            "any integrity or extraction issues."
        ),
        backstory=(
            "Forensic accounting specialist focused on validation accuracy and clear "
            "quality signals."
        ),
        tools=[read_financial_document],
        llm=llm,
        verbose=False,
        max_iter=3,
        max_rpm=30,
        allow_delegation=False,
    )

    financial_analyst = Agent(
        role="Senior Financial Analyst",
        goal=(
            "Extract key financial metrics and trends directly from verified document "
            "context and answer the user query with evidence-backed analysis."
        ),
        backstory=(
            "Experienced buy-side analyst specializing in fundamentals, trend analysis, "
            "and concise decision-grade reporting."
        ),
        tools=[search_tool],
        llm=llm,
        verbose=False,
        max_iter=5,
        max_rpm=30,
        allow_delegation=False,
    )

    investment_advisor = Agent(
        role="Certified Investment Advisor",
        goal=(
            "Translate financial findings into practical investment guidance across risk "
            "profiles, with explicit assumptions and disclaimers."
        ),
        backstory=(
            "Portfolio advisor focused on risk-adjusted recommendations grounded in "
            "documented fundamentals."
        ),
        tools=[analyze_investment_data, search_tool],
        llm=llm,
        verbose=False,
        max_iter=5,
        max_rpm=30,
        allow_delegation=False,
    )

    risk_assessor = Agent(
        role="Financial Risk Assessment Specialist",
        goal=(
            "Identify, categorize, and rate business/financial risks with practical "
            "mitigation actions tied to the document evidence."
        ),
        backstory=(
            "Risk management specialist experienced in market, credit, liquidity, "
            "operational, and regulatory risk frameworks."
        ),
        tools=[assess_risk_factors],
        llm=llm,
        verbose=False,
        max_iter=4,
        max_rpm=30,
        allow_delegation=False,
    )

    return verifier, financial_analyst, investment_advisor, risk_assessor


# Backward-compatible module-level agents for any legacy imports.
verifier, financial_analyst, investment_advisor, risk_assessor = build_agents()
