# backend/ingest/status.py
"""Shared utilities for tracking ingestion job status."""

import sys
import os
from datetime import datetime, timezone
from typing import Optional

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(CURRENT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from db import get_conn


def update_ingest_status(
    job_name: str,
    rows_inserted: int,
    error_message: Optional[str] = None,
) -> None:
    """
    Update the ingest_status table after a job run.

    Args:
        job_name: Unique identifier for the job (e.g., 'rss_ingest', 'crypto_backfill')
        rows_inserted: Number of rows inserted in this run
        error_message: If set, indicates the job failed; otherwise marks success
    """
    now = datetime.now(tz=timezone.utc)

    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                if error_message:
                    # Job failed
                    cur.execute(
                        """
                        INSERT INTO ingest_status (job_name, last_error, last_error_message, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (job_name) DO UPDATE SET
                            last_error = EXCLUDED.last_error,
                            last_error_message = EXCLUDED.last_error_message,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (job_name, now, error_message, now),
                    )
                else:
                    # Job succeeded
                    cur.execute(
                        """
                        INSERT INTO ingest_status (job_name, last_success, last_rows_inserted, updated_at)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (job_name) DO UPDATE SET
                            last_success = EXCLUDED.last_success,
                            last_rows_inserted = EXCLUDED.last_rows_inserted,
                            updated_at = EXCLUDED.updated_at
                        """,
                        (job_name, now, rows_inserted, now),
                    )
    except Exception as e:
        print(f"[ingest] ⚠️ Failed to update ingest_status for {job_name}: {e}")
