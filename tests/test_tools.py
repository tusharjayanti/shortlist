from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from tools.ats_scanner import (
    GreenhouseNotFound,
    filter_by_location,
    scan_ashby,
    scan_greenhouse,
    scan_lever,
)
from tools.browser import open_job_page
from tools.compiler import check_pdflatex_available, compile_pdf
from tools.resume import read_resume, write_tailored_resume
from tools.scraper import is_allowed_domain, jitter_delay

FIXTURE_CFG = Path(__file__).parent / "fixtures" / "test_config.yaml"


@pytest.fixture(scope="module")
def cfg():
    from tools.config_loader import load_config
    return load_config(str(FIXTURE_CFG))


# ── scraper: is_allowed_domain ──────────────────────────────────────────────

def test_is_allowed_domain_matches_exact():
    assert is_allowed_domain("https://razorpay.com/careers/123", ["razorpay.com"]) is True


def test_is_allowed_domain_strips_www():
    assert is_allowed_domain("https://www.razorpay.com/jobs/1", ["razorpay.com"]) is True


def test_is_allowed_domain_rejects_unknown_domain():
    assert is_allowed_domain("https://evil.com/phish", ["razorpay.com"]) is False


def test_is_allowed_domain_case_insensitive():
    assert is_allowed_domain("https://RAZORPAY.COM/jobs", ["razorpay.com"]) is True


# ── scraper: jitter_delay ────────────────────────────────────────────────────

def test_jitter_delay_respects_min_max(cfg):
    with patch("tools.scraper.time.sleep") as mock_sleep:
        for _ in range(30):
            jitter_delay(cfg)
        for call in mock_sleep.call_args_list:
            delay = call.args[0]
            assert cfg.sources.scraping.min_delay <= delay <= cfg.sources.scraping.max_delay


# ── ats_scanner: greenhouse ──────────────────────────────────────────────────

@respx.mock
def test_scan_greenhouse_parses_response():
    respx.get("https://boards-api.greenhouse.io/v1/boards/acme/jobs").mock(
        return_value=httpx.Response(200, json={
            "jobs": [
                {
                    "title": "Backend Engineer",
                    "location": {"name": "Bengaluru, India"},
                    "absolute_url": "https://boards.greenhouse.io/acme/jobs/123",
                    "updated_at": "2026-04-01T00:00:00Z",
                }
            ]
        })
    )
    jobs = scan_greenhouse("acme")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Backend Engineer"
    assert jobs[0]["location"] == "Bengaluru, India"
    assert jobs[0]["source"] == "greenhouse"


@respx.mock
def test_scan_greenhouse_404_returns_empty():
    respx.get("https://boards-api.greenhouse.io/v1/boards/missing/jobs").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(GreenhouseNotFound):
        scan_greenhouse("missing")


# ── ats_scanner: ashby ───────────────────────────────────────────────────────

@respx.mock
def test_scan_ashby_parses_response():
    respx.get("https://jobs.ashbyhq.com/api/non-user-facing/job-board/listing").mock(
        return_value=httpx.Response(200, json={
            "jobPostings": [
                {
                    "title": "Staff Engineer",
                    "location": "Bengaluru",
                    "id": "abc123",
                    "updatedAt": "2026-04-01",
                }
            ]
        })
    )
    jobs = scan_ashby("acme")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Staff Engineer"
    assert jobs[0]["url"] == "https://jobs.ashbyhq.com/acme/abc123"
    assert jobs[0]["source"] == "ashby"


# ── ats_scanner: lever ───────────────────────────────────────────────────────

@respx.mock
def test_scan_lever_parses_response():
    respx.get("https://api.lever.co/v0/postings/acme").mock(
        return_value=httpx.Response(200, json=[
            {
                "text": "Senior Engineer",
                "categories": {"location": "Bangalore"},
                "hostedUrl": "https://jobs.lever.co/acme/456",
                "createdAt": 1712000000000,
            }
        ])
    )
    jobs = scan_lever("acme")
    assert len(jobs) == 1
    assert jobs[0]["title"] == "Senior Engineer"
    assert jobs[0]["location"] == "Bangalore"
    assert jobs[0]["source"] == "lever"


# ── ats_scanner: filter_by_location ─────────────────────────────────────────

def test_filter_by_location_keeps_matching_jobs(cfg):
    jobs = [
        {"title": "SWE", "location": "Bengaluru, Karnataka"},
        {"title": "SRE", "location": "Mumbai, India"},
    ]
    result = filter_by_location(jobs, cfg)
    assert len(result) == 1
    assert result[0]["title"] == "SWE"


def test_filter_by_location_keeps_jobs_without_location(cfg):
    jobs = [
        {"title": "Remote SWE", "location": ""},
        {"title": "No loc SWE"},
    ]
    result = filter_by_location(jobs, cfg)
    assert len(result) == 2


# ── resume ───────────────────────────────────────────────────────────────────

def test_read_resume_returns_content(tmp_path):
    resume = tmp_path / "resume.tex"
    resume.write_text(r"\documentclass{article}\begin{document}Hello\end{document}")
    assert "Hello" in read_resume(str(resume))


def test_read_resume_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_resume(str(tmp_path / "nonexistent.tex"))


def test_write_tailored_resume_never_touches_original(tmp_path):
    original_file = tmp_path / "original.tex"
    original_content = "x" * 1000
    original_file.write_text(original_content)

    tailored = "y" * 900  # 90% — safely above 70%
    output = tmp_path / "out" / "tailored.tex"
    write_tailored_resume(original_content, tailored, str(output))

    assert original_file.read_text() == original_content
    assert output.read_text() == tailored


def test_write_tailored_resume_raises_if_too_short(tmp_path):
    original = "x" * 1000
    too_short = "y" * 699  # 69.9% — below 70%
    with pytest.raises(ValueError, match="less than 70%"):
        write_tailored_resume(original, too_short, str(tmp_path / "out.tex"))


# ── compiler ─────────────────────────────────────────────────────────────────

def test_check_pdflatex_available_returns_bool():
    assert isinstance(check_pdflatex_available(), bool)


@pytest.mark.skipif(not check_pdflatex_available(), reason="pdflatex not installed")
def test_compile_pdf_produces_pdf(tmp_path):
    tex = tmp_path / "hello.tex"
    tex.write_text(
        r"\documentclass{minimal}"
        r"\begin{document}Hello world\end{document}"
    )
    pdf = compile_pdf(str(tex), str(tmp_path / "output"))
    assert pdf.endswith(".pdf")
    assert Path(pdf).exists()


# ── browser ──────────────────────────────────────────────────────────────────

def test_open_job_page_rejects_http(cfg):
    assert open_job_page("http://razorpay.com/jobs/1", cfg) is False


def test_open_job_page_rejects_unknown_domain(cfg):
    assert open_job_page("https://evil.com/jobs/1", cfg) is False


def test_open_job_page_accepts_allowed_domain(cfg):
    with patch("tools.browser.webbrowser.open") as mock_open:
        result = open_job_page("https://razorpay.com/jobs/42", cfg)
    assert result is True
    mock_open.assert_called_once_with("https://razorpay.com/jobs/42")


def test_open_job_page_accepts_ats_domain(cfg):
    with patch("tools.browser.webbrowser.open") as mock_open:
        result = open_job_page("https://boards.greenhouse.io/acme/jobs/99", cfg)
    assert result is True
    mock_open.assert_called_once()
