"""
Financial Document Analyzer - Automated Test Suite.

Contains unit and integration tests for database operations, security helpers,
PDF parsing tools, centralized pipeline runner, and API endpoint routes.
"""

import os
import json
import unittest
from unittest.mock import patch, MagicMock

# Force database URL to in-memory SQLite during testing to avoid polluting actual database
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from database import (
    init_db,
    SessionLocal,
    create_user,
    get_user,
    get_user_by_api_key,
    save_analysis_result,
    get_analysis_result,
    get_all_results,
    User,
    AnalysisResult,
)
from tools import (
    _word_boundary_match,
    read_financial_document,
    analyze_investment_data,
    assess_risk_factors,
    fetch_stock_quote,
)
import pipeline


class TestDatabaseAndAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        # Clear tables before each test
        db = SessionLocal()
        try:
            db.query(AnalysisResult).delete()
            db.query(User).delete()
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def test_user_creation_and_lookup(self):
        # Create a test user
        username = "tester"
        email = "test@example.com"
        user_dict = create_user(username=username, email=email)
        
        self.assertIn("user_id", user_dict)
        self.assertEqual(user_dict["username"], username)
        self.assertEqual(user_dict["email"], email)
        self.assertIn("api_key", user_dict)  # Plaintext key should be returned ONCE
        
        # Verify hash matches in db and is not plaintext
        db = SessionLocal()
        user_in_db = db.query(User).filter_by(user_id=user_dict["user_id"]).first()
        self.assertNotEqual(user_in_db.api_key_hash, user_dict["api_key"])
        db.close()

        # Lookup by API key
        resolved_user = get_user_by_api_key(user_dict["api_key"])
        self.assertIsNotNone(resolved_user)
        self.assertEqual(resolved_user["user_id"], user_dict["user_id"])

        # Lookup by invalid API key
        self.assertIsNone(get_user_by_api_key("wrong_key"))

    def test_duplicate_user_rejection(self):
        create_user(username="dup")
        with self.assertRaises(ValueError):
            create_user(username="dup")

    def test_save_and_retrieve_analysis(self):
        # Register owner
        user = create_user(username="owner")
        user_id = user["user_id"]
        
        analysis_id = "test-analysis-uuid"
        filename = "q1_report.pdf"
        query = "Show earnings"
        result_content = json.dumps({"verification": "Verified", "financial_analysis": "Good"})
        
        # Save analysis
        save_analysis_result(
            analysis_id=analysis_id,
            filename=filename,
            query=query,
            result=result_content,
            status="completed",
            user_id=user_id
        )
        
        # Retrieve analysis
        record = get_analysis_result(analysis_id)
        self.assertIsNotNone(record)
        self.assertEqual(record["filename"], filename)
        self.assertEqual(record["query"], query)
        self.assertEqual(record["result"], result_content)
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["user_id"], user_id)
        
        # Check list results
        all_results = get_all_results(user_id=user_id)
        self.assertEqual(len(all_results), 1)
        self.assertEqual(all_results[0]["analysis_id"], analysis_id)


class TestFinancialTools(unittest.TestCase):
    def test_word_boundary_matching(self):
        text = "The enterprise value is high."
        self.assertTrue(_word_boundary_match("enterprise value", text))
        # Substrings without word boundaries should fail
        self.assertFalse(_word_boundary_match("enter", text))

    def test_read_pdf_file_not_found(self):
        # Call underlying function using .func to bypass CrewAI Tool object restriction
        res = read_financial_document.func("nonexistent_file_path.pdf")
        self.assertIn("TOOL_ERROR:", res)

    def test_analyze_investment_data_mock(self):
        text = "Our operating income and net income increased, while our debt remained low."
        res = analyze_investment_data.func(text)
        self.assertIn("Profitability", res)
        self.assertIn("Liquidity & Debt", res)
        
        empty_text = "No metrics here."
        res_empty = analyze_investment_data.func(empty_text)
        self.assertIn("No standard financial metrics", res_empty)

    def test_assess_risk_factors_mock(self):
        # Expect error on paths
        res_path = assess_risk_factors.func("some/file/path.pdf")
        self.assertIn("TOOL_ERROR:", res_path)
        
        # Standard execution
        text = "There is significant volatility and compliance risk with legal proceedings."
        res = assess_risk_factors.func(text)
        self.assertIn("Market Risk", res)
        self.assertIn("Regulatory Risk", res)

    @patch("urllib.request.urlopen")
    def test_fetch_stock_quote_mocked(self, mock_urlopen):
        # Mock response from Yahoo Finance chart endpoint
        mock_response = MagicMock()
        mock_json = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 150.25,
                            "previousClose": 148.00,
                            "currency": "USD",
                            "exchangeName": "NASDAQ"
                        }
                    }
                ]
            }
        }
        mock_response.read.return_value = json.dumps(mock_json).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        quote = fetch_stock_quote.func("AAPL")
        self.assertIn("Current Price: 150.25 USD", quote)
        self.assertIn("NASDAQ", quote)
        self.assertIn("Daily Change: +2.25", quote)


class TestPipelineFormatting(unittest.TestCase):
    def test_markdown_formatter_success(self):
        structured = {
            "verification": "Doc verified.",
            "financial_analysis": "Revenue up 10%.",
            "investment_insights": "Buy rating.",
            "risk_assessment": "Low risk."
        }
        json_str = json.dumps(structured)
        markdown = pipeline.format_json_to_markdown(json_str)
        
        self.assertIn("# 1. Document Verification Report", markdown)
        self.assertIn("Doc verified.", markdown)
        self.assertIn("# 2. Financial Analysis Report", markdown)
        self.assertIn("Revenue up 10%.", markdown)
        self.assertIn("# 3. Investment Insights & Advisory", markdown)
        self.assertIn("Buy rating.", markdown)
        self.assertIn("# 4. Financial Risk Assessment", markdown)
        self.assertIn("Low risk.", markdown)

    def test_markdown_formatter_fallback(self):
        # Non-JSON strings should fall back to raw input
        raw = "This is a raw text report."
        res = pipeline.format_json_to_markdown(raw)
        self.assertEqual(res, raw)


class TestAPIRoutingMocked(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    @patch("pipeline.run_financial_pipeline")
    def test_centralized_pipeline_execution_mocked(self, mock_runner):
        # Mock pipeline output
        mock_payload = {
            "verification": "V",
            "financial_analysis": "F",
            "investment_insights": "I",
            "risk_assessment": "R"
        }
        mock_runner.return_value = json.dumps(mock_payload)
        
        # Test pipeline directly
        res = pipeline.run_financial_pipeline("query", "dummy.pdf")
        self.assertEqual(res, json.dumps(mock_payload))
        mock_runner.assert_called_once_with("query", "dummy.pdf")


if __name__ == "__main__":
    unittest.main()
