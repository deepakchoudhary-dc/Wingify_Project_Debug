"""
Financial Document Analyzer - Celery Worker Tasks.

Defines Celery tasks for asynchronous financial document analysis.
"""

import logging
import os

from celery_config import celery_app
from database import init_db, save_analysis_result

logger = logging.getLogger(__name__)

# Ensure DB schema exists when the worker process starts.
init_db()


def _cleanup_file(path: str) -> None:
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            logger.warning("Failed to remove temporary upload file: %s", path)


@celery_app.task(bind=True, name="analyze_document", max_retries=2, default_retry_delay=30)
def analyze_document_task(
    self,
    query: str,
    file_path: str,
    analysis_id: str,
    filename: str,
    user_id: str | None = None,
):
    """
    Run the full financial analysis crew asynchronously via Celery.
    """
    try:
        save_analysis_result(
            analysis_id=analysis_id,
            filename=filename,
            query=query,
            result="Analysis in progress...",
            status="processing",
            user_id=user_id,
        )

        # Import inside task function to avoid import cycles at startup.
        from crewai import Crew, Process
        from agents import build_agents
        from task import build_financial_tasks

        verifier, financial_analyst, investment_advisor, risk_assessor = build_agents()
        tasks = build_financial_tasks(verifier, financial_analyst, investment_advisor, risk_assessor)
        financial_crew = Crew(
            agents=[verifier, financial_analyst, investment_advisor, risk_assessor],
            tasks=tasks,
            process=Process.sequential,
            verbose=False,
        )

        result = financial_crew.kickoff(inputs={"query": query, "file_path": file_path})
        analysis_text = str(result)

        if "TOOL_ERROR:" in analysis_text:
            raise RuntimeError("Analysis pipeline encountered tool failure.")

        save_analysis_result(
            analysis_id=analysis_id,
            filename=filename,
            query=query,
            result=analysis_text,
            status="completed",
            user_id=user_id,
        )

        _cleanup_file(file_path)
        return {"status": "completed", "analysis_id": analysis_id, "result": analysis_text}

    except Exception as exc:
        if self.request.retries >= self.max_retries:
            logger.exception("Celery analysis failed permanently")
            save_analysis_result(
                analysis_id=analysis_id,
                filename=filename,
                query=query,
                result="Analysis failed after retry attempts.",
                status="failed",
                user_id=user_id,
            )
            _cleanup_file(file_path)
            raise

        save_analysis_result(
            analysis_id=analysis_id,
            filename=filename,
            query=query,
            result=(
                f"Analysis attempt {self.request.retries + 1} failed; "
                "retrying in background."
            ),
            status="retrying",
            user_id=user_id,
        )
        raise self.retry(exc=exc)
