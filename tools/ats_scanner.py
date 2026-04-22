from __future__ import annotations

import httpx
from rich.console import Console

console = Console()


class GreenhouseNotFound(Exception):
    pass


def scan_greenhouse(slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
    try:
        resp = httpx.get(url, timeout=15.0)
    except httpx.RequestError as e:
        console.print(f"[yellow]greenhouse/{slug}: request error: {e}[/yellow]")
        return []

    if resp.status_code == 404:
        raise GreenhouseNotFound(f"Greenhouse board not found: {slug}")

    if resp.status_code != 200:
        console.print(f"[yellow]greenhouse/{slug}: HTTP {resp.status_code}[/yellow]")
        return []

    return [
        {
            "title": job.get("title", ""),
            "location": job.get("location", {}).get("name", ""),
            "url": job.get("absolute_url", ""),
            "updated_at": job.get("updated_at", ""),
            "source": "greenhouse",
        }
        for job in resp.json().get("jobs", [])
    ]


def scan_ashby(slug: str) -> list[dict]:
    url = "https://jobs.ashbyhq.com/api/non-user-facing/job-board/listing"
    try:
        resp = httpx.get(
            url,
            params={"organizationHostedJobsPageName": slug},
            timeout=15.0,
        )
    except httpx.RequestError as e:
        console.print(f"[yellow]ashby/{slug}: request error: {e}[/yellow]")
        return []

    if resp.status_code != 200:
        return []

    return [
        {
            "title": job.get("title", ""),
            "location": job.get("location", ""),
            "url": f"https://jobs.ashbyhq.com/{slug}/{job.get('id', '')}",
            "updated_at": job.get("updatedAt", ""),
            "source": "ashby",
        }
        for job in resp.json().get("jobPostings", [])
    ]


def scan_lever(slug: str) -> list[dict]:
    try:
        resp = httpx.get(
            f"https://api.lever.co/v0/postings/{slug}",
            params={"mode": "json"},
            timeout=15.0,
        )
    except httpx.RequestError as e:
        console.print(f"[yellow]lever/{slug}: request error: {e}[/yellow]")
        return []

    if resp.status_code != 200:
        return []

    return [
        {
            "title": job.get("text", ""),
            "location": job.get("categories", {}).get("location", ""),
            "url": job.get("hostedUrl", ""),
            "updated_at": str(job.get("createdAt", "")),
            "source": "lever",
        }
        for job in resp.json()
    ]


def scan_all_ats(config) -> list[dict]:
    all_jobs: list[dict] = []
    seen: set[str] = set()

    scanners = [
        ("greenhouse", scan_greenhouse, config.sources.ats.greenhouse),
        ("ashby", scan_ashby, config.sources.ats.ashby),
        ("lever", scan_lever, config.sources.ats.lever),
    ]

    for platform, scanner, slugs in scanners:
        for slug in slugs:
            try:
                jobs = scanner(slug)
                new = [j for j in jobs if j["url"] not in seen]
                seen.update(j["url"] for j in new)
                all_jobs.extend(new)
                console.print(f"[green]{platform}/{slug}:[/green] {len(new)} jobs")
            except Exception as e:
                console.print(f"[red]{platform}/{slug}: failed — {e}[/red]")

    return all_jobs


def filter_by_location(jobs: list[dict], config) -> list[dict]:
    result = []
    for job in jobs:
        loc = job.get("location") or ""
        if not loc or config.matches_location(loc):
            result.append(job)
    return result
