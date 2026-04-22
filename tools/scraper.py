from __future__ import annotations

import random
import time
import urllib.parse

import httpx
from bs4 import BeautifulSoup

_GATED_MARKERS = ("sign in", "log in", "please authenticate")


def is_allowed_domain(url: str, allowed: list[str]) -> bool:
    hostname = (urllib.parse.urlparse(url).hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return any(
        hostname == d.lower() or hostname.endswith("." + d.lower())
        for d in allowed
    )


def jitter_delay(config) -> None:
    base = config.sources.scraping.delay_seconds
    min_d = config.sources.scraping.min_delay
    max_d = config.sources.scraping.max_delay
    delay = random.uniform(base * 0.5, base * 2.0)
    delay += random.gauss(0, 0.3)
    delay = max(min_d, min(delay, max_d))
    time.sleep(delay)


def fetch_job(url: str, config) -> dict:
    if not is_allowed_domain(url, config.sources.scraping.allowed_domains):
        return {"blocked": True, "reason": f"Domain not in allowed list: {url}"}

    jitter_delay(config)

    user_agent = random.choice(config.sources.scraping.user_agents)

    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=10.0,
            follow_redirects=True,
        )
    except httpx.RequestError:
        return {"gated": True, "url": url}

    if resp.status_code >= 400:
        return {"gated": True, "url": url}

    soup = BeautifulSoup(resp.text, "html.parser")

    # Check for gated markers before stripping structural tags
    if any(marker in soup.get_text(" ", strip=True).lower() for marker in _GATED_MARKERS):
        return {"gated": True, "url": url}

    for tag in soup.find_all(["nav", "footer", "header", "script", "style"]):
        tag.decompose()

    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else ""
    if not title:
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

    main = soup.find("main") or soup.find("article")
    description = (main or soup).get_text(" ", strip=True)

    parsed = urllib.parse.urlparse(url)
    source = (parsed.hostname or "").lstrip("www.")

    return {
        "title": title,
        "description": description,
        "url": url,
        "source": source,
        "gated": False,
    }
