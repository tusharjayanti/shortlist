from __future__ import annotations

import urllib.parse
import webbrowser

from rich.console import Console

console = Console()

_ATS_DOMAINS = frozenset({"boards.greenhouse.io", "jobs.ashbyhq.com", "jobs.lever.co"})


def open_job_page(url: str, config) -> bool:
    if not url.startswith("https://"):
        console.print(f"[red]Blocked: URL must use https — {url}[/red]")
        return False

    hostname = (urllib.parse.urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]

    allowed = {d.lower() for d in config.sources.scraping.allowed_domains}
    domain_ok = any(hostname == d or hostname.endswith("." + d) for d in allowed)

    if not (domain_ok or hostname in _ATS_DOMAINS):
        console.print(f"[red]Blocked: domain not permitted — {hostname}[/red]")
        return False

    webbrowser.open(url)
    return True
