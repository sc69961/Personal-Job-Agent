"""
sheets_writer.py — Writes scored job results to Google Sheets.
Deduplicates by job ID so re-runs don't create duplicates.
Keeps a tab for "Active" jobs and archives old ones.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

SHEET_HEADERS = [
    "Score", "Recommendation", "Title", "Company", "Company Tier",
    "Location", "Salary Info", "Title Match", "Location OK", "Salary OK",
    "Senior OK", "Target Co", "Top Strengths", "Top Gaps",
    "Match Summary", "Source", "Posted Date", "URL", "Job ID", "Scraped At",
]

def get_sheets_client(credentials_path: str):
    """Return an authenticated gspread client."""
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    return gspread.authorize(creds)


def job_to_row(job: dict) -> list:
    """Convert a job dict to a Sheet row (order matches SHEET_HEADERS)."""
    return [
        job.get("score", ""),
        job.get("apply_recommendation", ""),
        job.get("title", ""),
        job.get("company", ""),
        job.get("company_tier", ""),
        job.get("location", ""),
        job.get("salary_text", ""),
        job.get("title_match", ""),
        str(job.get("location_ok", "")),
        str(job.get("salary_ok", "")),
        str(job.get("seniority_ok", "")),
        str(job.get("is_target_company", "")),
        " | ".join(job.get("top_strengths", [])),
        " | ".join(job.get("top_gaps", [])),
        job.get("match_summary", ""),
        job.get("source", ""),
        job.get("posted_date", ""),
        job.get("url", ""),
        job.get("id", ""),
        job.get("scraped_at", ""),
    ]


def write_to_sheet(jobs: list[dict], sheet_id: str, credentials_path: str) -> int:
    """
    Write scored jobs to Google Sheet. Returns count of new rows added.
    - Creates "Active Jobs" tab if missing
    - Deduplicates by Job ID column
    - Sorts by score descending
    - Adds header row if sheet is empty
    """
    try:
        gc = get_sheets_client(credentials_path)
        sh = gc.open_by_key(sheet_id)
    except Exception as e:
        logger.error(f"Could not open Google Sheet {sheet_id}: {e}")
        return 0

    # Get or create "Active Jobs" worksheet
    try:
        ws = sh.worksheet("Active Jobs")
    except Exception:
        ws = sh.add_worksheet(title="Active Jobs", rows=1000, cols=len(SHEET_HEADERS))

    # Load existing data to check for duplicates
    existing_rows = ws.get_all_values()
    if not existing_rows:
        # Write headers
        ws.append_row(SHEET_HEADERS)
        existing_ids = set()
    else:
        try:
            id_col_index = SHEET_HEADERS.index("Job ID")
            existing_ids = {row[id_col_index] for row in existing_rows[1:] if len(row) > id_col_index}
        except (ValueError, IndexError):
            existing_ids = set()

    # Only write new jobs
    new_rows = []
    for job in jobs:
        if job.get("id") not in existing_ids:
            new_rows.append(job_to_row(job))

    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        logger.info(f"Wrote {len(new_rows)} new jobs to Google Sheet")

        # Re-sort all rows by score (column 0) descending
        _sort_sheet_by_score(ws)
    else:
        logger.info("No new jobs to write (all already in sheet)")

    return len(new_rows)


def _sort_sheet_by_score(ws) -> None:
    """Re-sort the sheet rows by score column, descending. Keeps header row."""
    try:
        all_rows = ws.get_all_values()
        if len(all_rows) < 3:
            return
        header = all_rows[0]
        data_rows = all_rows[1:]
        try:
            score_idx = header.index("Score")
            data_rows.sort(key=lambda r: int(r[score_idx]) if r[score_idx].isdigit() else 0, reverse=True)
        except (ValueError, IndexError):
            return
        # Clear and rewrite
        ws.clear()
        ws.append_row(header)
        ws.append_rows(data_rows)
    except Exception as e:
        logger.warning(f"Could not sort sheet: {e}")


def format_sheet_header(ws) -> None:
    """Apply basic formatting: bold header, freeze top row, color by score."""
    try:
        import gspread_formatting as gsf
        header_fmt = gsf.CellFormat(
            backgroundColor=gsf.Color(0.2, 0.4, 0.6),
            textFormat=gsf.TextFormat(bold=True, foregroundColor=gsf.Color(1, 1, 1)),
        )
        gsf.format_cell_range(ws, "1:1", header_fmt)
        ws.freeze(rows=1)
    except ImportError:
        pass  # gspread_formatting is optional
    except Exception as e:
        logger.debug(f"Formatting skipped: {e}")
