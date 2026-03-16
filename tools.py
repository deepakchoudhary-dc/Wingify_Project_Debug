"""
Financial Document Analyzer - CrewAI tools.
"""

import os
import re

from dotenv import load_dotenv
from crewai.tools import tool
from crewai_tools import SerperDevTool

load_dotenv()


def _env_positive_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        return default


MAX_EXTRACT_CHARS = _env_positive_int("MAX_EXTRACT_CHARS", 150000)

# Real-time web search for market context.
if os.getenv("SERPER_API_KEY"):
    search_tool = SerperDevTool()
else:
    @tool("Search Internet")
    def search_tool(query: str) -> str:
        """Fallback mock search tool when SERPER_API_KEY is not set."""
        return "Search feature is disabled (no API key). Proceed using only the document context."

def _word_boundary_match(keyword: str, text: str) -> bool:
    """Match whole terms only to avoid substring false positives."""
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return bool(re.search(pattern, text))


@tool("Read Financial Document")
def read_financial_document(file_path: str) -> str:
    """Read and extract text from a PDF file."""
    from pypdf import PdfReader

    if not os.path.exists(file_path):
        return f"TOOL_ERROR: File not found at path '{file_path}'."

    try:
        reader = PdfReader(file_path)
        if len(reader.pages) == 0:
            return "TOOL_ERROR: The PDF file contains no pages."

        full_report = []
        current_len = 0
        truncated = False

        for page_num, page in enumerate(reader.pages, start=1):
            content = page.extract_text() or ""
            if not content.strip():
                continue

            while "\n\n\n" in content:
                content = content.replace("\n\n\n", "\n\n")

            page_text = f"\n--- Page {page_num} ---\n{content}\n"
            next_len = current_len + len(page_text)

            if next_len > MAX_EXTRACT_CHARS:
                remaining = MAX_EXTRACT_CHARS - current_len
                if remaining > 0:
                    full_report.append(page_text[:remaining])
                truncated = True
                break

            full_report.append(page_text)
            current_len = next_len

        extracted = "".join(full_report).strip()
        if not extracted:
            return (
                "TOOL_ERROR: No text content could be extracted from the PDF. "
                "The file may be scanned/image-based."
            )

        if truncated:
            extracted += (
                "\n\n[TRUNCATED] Document text was cut to stay within the "
                f"{MAX_EXTRACT_CHARS} character processing limit."
            )

        return extracted
    except Exception as exc:
        return f"TOOL_ERROR: Failed to read PDF file: {exc}"


@tool("Analyze Investment Data")
def analyze_investment_data(financial_data: str) -> str:
    """Extract broad investment-related metrics/terms from text."""
    processed_data = " ".join(financial_data.split())
    lower_data = processed_data.lower()

    metric_categories = {
        "Profitability": [
            "revenue",
            "net income",
            "gross profit",
            "operating income",
            "profit margin",
            "gross margin",
            "operating margin",
            "ebitda",
        ],
        "Per-Share Metrics": [
            "earnings per share",
            "eps",
            "dividend",
            "book value per share",
        ],
        "Valuation": [
            "p/e",
            "price-to-earnings",
            "p/b",
            "price-to-book",
            "ev/ebitda",
            "market cap",
            "enterprise value",
        ],
        "Growth": [
            "growth",
            "yoy",
            "year-over-year",
            "quarter-over-quarter",
            "cagr",
        ],
        "Liquidity & Debt": [
            "cash flow",
            "free cash flow",
            "debt",
            "leverage",
            "current ratio",
            "quick ratio",
            "debt-to-equity",
        ],
        "Returns": [
            "roi",
            "roe",
            "roa",
            "return on equity",
            "return on assets",
            "return on investment",
        ],
        "Balance Sheet": [
            "total assets",
            "total liabilities",
            "equity",
            "working capital",
            "goodwill",
            "intangible assets",
        ],
    }

    found_metrics = {}
    for category, keywords in metric_categories.items():
        matches = [kw for kw in keywords if _word_boundary_match(kw, lower_data)]
        if matches:
            found_metrics[category] = matches

    if not found_metrics:
        return (
            "No standard financial metrics were detected in the provided text. "
            "The data may be non-standard and require manual review."
        )

    summary_parts = [f"  {category}: {', '.join(matches)}" for category, matches in found_metrics.items()]
    summary = "\n".join(summary_parts)
    return (
        f"Key financial metrics identified in the document:\n{summary}\n\n"
        f"Total metric categories found: {len(found_metrics)}/{len(metric_categories)}."
    )


@tool("Assess Risk Factors")
def assess_risk_factors(financial_data: str) -> str:
    """Identify risk-related terms and classify risk categories."""
    import os
    # Guard: reject file paths — this tool expects document text, not a path.
    if os.path.exists(financial_data) or (len(financial_data) < 500 and ("/" in financial_data or "\\" in financial_data)):
        return (
            "TOOL_ERROR: 'Assess Risk Factors' received what looks like a file path instead of "
            "document text. Extract the document body text from the verification task context "
            "and pass that string directly to this tool."
        )
    lower_data = financial_data.lower()

    risk_categories = {
        "Market Risk": [
            "market risk",
            "volatility",
            "interest rate",
            "currency risk",
            "exchange rate",
            "commodity price",
            "market downturn",
            "bear market",
        ],
        "Credit Risk": [
            "credit risk",
            "default",
            "counterparty",
            "credit rating",
            "downgrade",
            "bad debt",
            "write-off",
        ],
        "Operational Risk": [
            "operational risk",
            "supply chain",
            "cybersecurity",
            "data breach",
            "system failure",
            "disruption",
            "workforce",
        ],
        "Regulatory Risk": [
            "regulatory",
            "compliance",
            "legislation",
            "legal proceedings",
            "litigation",
            "sec filing",
            "sec report",
            "government",
            "sanctions",
            "antitrust",
        ],
        "Financial Risk": [
            "debt",
            "leverage",
            "liquidity",
            "cash flow risk",
            "insolvency",
            "refinancing",
            "covenant",
            "impairment",
            "restructuring",
        ],
        "Competitive Risk": [
            "competition",
            "market share",
            "competitive pressure",
            "new entrants",
            "disruption",
            "innovation",
        ],
        "Macroeconomic Risk": [
            "recession",
            "inflation",
            "deflation",
            "unemployment",
            "gdp",
            "economic downturn",
            "geopolitical",
            "tariff",
            "trade war",
        ],
    }

    found_risks = {}
    for category, keywords in risk_categories.items():
        matches = [kw for kw in keywords if _word_boundary_match(kw, lower_data)]
        if matches:
            found_risks[category] = matches

    if not found_risks:
        return (
            "No prominent risk keywords were detected. This is not proof of low risk; "
            "manual review is still recommended."
        )

    summary_parts = []
    for category, matches in found_risks.items():
        if len(matches) >= 3:
            severity = "High"
        elif len(matches) >= 2:
            severity = "Medium"
        else:
            severity = "Low"
        summary_parts.append(f"  [{severity}] {category}: {', '.join(matches)}")

    summary = "\n".join(summary_parts)
    return (
        f"Risk factors identified in the document:\n{summary}\n\n"
        f"Total risk categories flagged: {len(found_risks)}/{len(risk_categories)}."
    )
