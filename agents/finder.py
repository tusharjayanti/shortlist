import logging
from dataclasses import dataclass, field
from urllib.parse import urlparse

import feedparser

from rich.console import Console
from rich.table import Table

from tools.ats_scanner import filter_by_location, scan_all_ats
from tools.config_loader import Config
from tools.scraper import fetch_job, jitter_delay
from tracker.audit import audited
from tracker.tracker import JobTracker


@dataclass
class SourceResult:
    source: str
    jobs_found: int
    jobs_new: int
    jobs_kept: int
    error: str | None = None


class FinderAgent:
    def __init__(self, tracker: JobTracker, config: Config):
        self.tracker = tracker
        self.config = config
        self.console = Console()

    @audited(agent_name="finder", action="discover_jobs")
    def run(self, app_id: str | None = None) -> list[dict]:
        """
        Discover jobs from all configured sources.

        app_id is optional because finder runs before any application
        exists — pass None and the audit log will record a discovery run.

        Returns list of deduplicated, location-filtered job dicts:
          {title, company, url, source, location, description, posted_at}
        """
        all_jobs: list[dict] = []
        results: list[SourceResult] = []

        ats_result = self._discover_ats()
        all_jobs.extend(ats_result["jobs"])
        results.append(ats_result["result"])

        rss_result = self._discover_rss()
        all_jobs.extend(rss_result["jobs"])
        results.append(rss_result["result"])

        scrape_result = self._discover_scraping()
        all_jobs.extend(scrape_result["jobs"])
        results.append(scrape_result["result"])

        final_jobs = self._finalize(all_jobs)
        self._print_summary(results, len(final_jobs))
        return final_jobs

    def _discover_ats(self) -> dict:
        """Zero-token ATS scanning via Greenhouse/Ashby/Lever APIs."""
        try:
            jobs = scan_all_ats(self.config)
            filtered = filter_by_location(jobs, self.config)
            for job in filtered:
                job.setdefault("company", "")
            new_jobs = self._filter_unseen(filtered, source_label="ats")
            return {
                "jobs": new_jobs,
                "result": SourceResult(
                    source="ats",
                    jobs_found=len(jobs),
                    jobs_new=len(new_jobs),
                    jobs_kept=len(new_jobs),
                ),
            }
        except Exception as e:
            logging.exception("ATS scan failed")
            return {
                "jobs": [],
                "result": SourceResult(
                    source="ats", jobs_found=0, jobs_new=0,
                    jobs_kept=0, error=str(e),
                ),
            }

    def _discover_rss(self) -> dict:
        """Fetch each configured RSS feed and parse entries."""
        all_jobs: list[dict] = []
        for feed_url in self.config.sources.rss:
            try:
                feed = feedparser.parse(feed_url)
                company = self._extract_company_from_feed(feed_url) or "Unknown"
                for entry in feed.entries:
                    all_jobs.append({
                        "title": entry.get("title", ""),
                        "company": company,
                        "url": entry.get("link", ""),
                        "location": entry.get("summary", ""),
                        "description": entry.get("summary", ""),
                        "source": f"rss:{company}",
                        "posted_at": entry.get("published", ""),
                    })
            except Exception:
                logging.exception(f"RSS feed failed: {feed_url}")

        new_jobs = self._filter_unseen(all_jobs, source_label="rss")
        return {
            "jobs": new_jobs,
            "result": SourceResult(
                source="rss",
                jobs_found=len(all_jobs),
                jobs_new=len(new_jobs),
                jobs_kept=len(new_jobs),
            ),
        }

    def _discover_scraping(self) -> dict:
        """
        Placeholder for per-domain listing-page scrapers.
        fetch_job() from tools/scraper.py handles individual known URLs;
        full listing-page discovery is added per company as needed.
        """
        return {
            "jobs": [],
            "result": SourceResult(
                source="scrape", jobs_found=0, jobs_new=0, jobs_kept=0,
            ),
        }

    def _filter_unseen(self, jobs: list[dict], source_label: str) -> list[dict]:
        """
        Remove jobs whose URL is already in seen_urls.
        Mark each new URL as seen as it passes through.
        """
        new_jobs = []
        for job in jobs:
            url = job.get("url", "")
            if not url:
                continue
            if self.tracker.is_seen_url(url):
                continue
            self.tracker.mark_url_seen(url, source=source_label)
            new_jobs.append(job)
        return new_jobs

    def _finalize(self, jobs: list[dict]) -> list[dict]:
        """
        Final pass across all sources:
          1. Deduplicate by URL (job may appear in multiple sources)
          2. Remove blacklisted companies (Tier 3)
        """
        seen_urls: set[str] = set()
        final = []
        for job in jobs:
            url = job.get("url", "")
            company = job.get("company", "")
            if not company.strip():
                logging.debug(f"finder: skipping job with no company: {url}")
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            if self.config.is_blacklisted(company):
                continue
            final.append(job)
        return final

    def _extract_company_from_feed(self, feed_url: str) -> str:
        """Best-effort company name from an RSS feed URL."""
        if "google.com" in feed_url:
            return "Google"
        if "atlassian.com" in feed_url:
            return "Atlassian"
        host = urlparse(feed_url).hostname or ""
        return host.split(".")[0].title()

    def _print_summary(
        self,
        results: list[SourceResult],
        final_count: int,
    ) -> None:
        table = Table(
            title=f"Job discovery complete — {final_count} jobs in shortlist",
            show_lines=True,
        )
        table.add_column("Source")
        table.add_column("Found")
        table.add_column("New (unseen)")
        table.add_column("Kept")
        table.add_column("Status")
        for r in results:
            status = "✓" if r.error is None else f"✗ {r.error[:40]}"
            table.add_row(
                r.source,
                str(r.jobs_found),
                str(r.jobs_new),
                str(r.jobs_kept),
                status,
            )
        self.console.print(table)
