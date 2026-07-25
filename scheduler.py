"""
Background scheduler: runs the NCLAT scraper every 30 min between 16:00–20:00 IST.

IST = UTC+5:30. APScheduler cron triggers use server-local time by default,
so if the server is configured to IST this works as-is. If the server is UTC,
change HOUR_START/HOUR_END to 10/14 (UTC equivalent of 16:00–20:00 IST).

To change the scraping window, edit HOUR_START and HOUR_END below.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scraping window (24-hour, server-local time)
# ---------------------------------------------------------------------------
HOUR_START = 16   # 4:00 PM
HOUR_END   = 20   # 8:00 PM (last run at 20:00)
INTERVAL_MINUTES = 30


def _scrape_job():
    """Thin wrapper so APScheduler can import without circular deps."""
    from scraper import run_scrape
    logger.info("Scheduled scrape starting")
    result = run_scrape()
    logger.info("Scheduled scrape done: %s", result)


def start_scheduler() -> BackgroundScheduler:
    """
    Create and start the background scheduler.
    Returns the scheduler instance (keep a reference so it isn't GC'd).
    """
    scheduler = BackgroundScheduler(
        job_defaults={"misfire_grace_time": 300, "coalesce": True},
        timezone="Asia/Kolkata",  # IST
    )

    # Fire at :00 and :30 of every hour between HOUR_START and HOUR_END
    scheduler.add_job(
        _scrape_job,
        trigger=CronTrigger(
            hour=f"{HOUR_START}-{HOUR_END}",
            minute=f"0/{INTERVAL_MINUTES}",
        ),
        id="nclat_scrape",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — NCLAT scrape runs %02d:00–%02d:00 IST every %d min",
        HOUR_START, HOUR_END, INTERVAL_MINUTES,
    )
    return scheduler
