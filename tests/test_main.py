from unittest.mock import MagicMock, patch

import pytest

from main import Shortlist


@pytest.fixture
def app():
    a = Shortlist()
    a.config = MagicMock()
    a.tracker = MagicMock()
    return a


# ── bootstrap ─────────────────────────────────────────────────────────────────

def test_bootstrap_fails_on_missing_config():
    """Bootstrap returns False if config.yaml missing."""
    a = Shortlist()
    with patch("main.load_config", side_effect=FileNotFoundError("not found")):
        result = a.bootstrap()
    assert result is False


def test_bootstrap_fails_on_llm_init_error():
    """Bootstrap returns False if init_llm raises."""
    a = Shortlist()
    with patch("main.load_config", return_value=MagicMock()), \
         patch("main.init_llm", side_effect=Exception("auth error")):
        result = a.bootstrap()
    assert result is False


def test_bootstrap_fails_on_db_connection_error():
    """Bootstrap returns False if tracker can't connect to DB."""
    a = Shortlist()
    with patch("main.load_config", return_value=MagicMock()), \
         patch("main.init_llm"), \
         patch("main.JobTracker", side_effect=Exception("connection refused")):
        result = a.bootstrap()
    assert result is False


# ── menu routing ──────────────────────────────────────────────────────────────

def test_run_menu_choice_q_returns_false(app):
    """Choosing 'q' signals quit."""
    assert app.run_menu_choice("q") is False


def test_run_menu_choice_1_calls_evaluate_job(app):
    app._evaluate_job = MagicMock()
    app.run_menu_choice("1")
    app._evaluate_job.assert_called_once()


def test_run_menu_choice_2_calls_proactive_scan(app):
    app._proactive_scan = MagicMock()
    app.run_menu_choice("2")
    app._proactive_scan.assert_called_once()


def test_run_menu_choice_3_calls_resume(app):
    app._resume_application = MagicMock()
    app.run_menu_choice("3")
    app._resume_application.assert_called_once()


def test_run_menu_choice_4_calls_status(app):
    app._show_status = MagicMock()
    app.run_menu_choice("4")
    app._show_status.assert_called_once()


def test_run_menu_choice_5_calls_audit(app):
    app._show_audit = MagicMock()
    app.run_menu_choice("5")
    app._show_audit.assert_called_once()


def test_run_menu_choice_6_calls_grades(app):
    app._show_grades = MagicMock()
    app.run_menu_choice("6")
    app._show_grades.assert_called_once()


def test_run_menu_choice_7_calls_costs(app):
    app._show_costs = MagicMock()
    app.run_menu_choice("7")
    app._show_costs.assert_called_once()


# ── error handling ────────────────────────────────────────────────────────────

def test_keyboard_interrupt_returns_to_menu(app):
    """Ctrl+C inside an action returns to menu, doesn't crash."""
    app._evaluate_job = MagicMock(side_effect=KeyboardInterrupt())
    assert app.run_menu_choice("1") is True


def test_action_exception_returns_to_menu(app):
    """Exceptions inside actions return to menu, don't propagate."""
    app._evaluate_job = MagicMock(side_effect=ValueError("oops"))
    assert app.run_menu_choice("1") is True


# ── result summaries ──────────────────────────────────────────────────────────

def test_summarize_completed_status(app, capsys):
    """Completed status prints success panel."""
    app._summarize_reactive_result({
        "status": "completed",
        "score": 11,
        "grade": "A",
        "archetype": "fintech_platform",
        "resume_pdf": "/tmp/x.pdf",
    })
    captured = capsys.readouterr()
    assert "Completed" in captured.out


def test_summarize_below_threshold_status(app, capsys):
    app._summarize_reactive_result({
        "status": "scored_below_threshold",
        "score": 5,
        "grade": "F",
    })
    captured = capsys.readouterr()
    assert "Below threshold" in captured.out


def test_summarize_duplicate_status(app, capsys):
    app._summarize_reactive_result({
        "status": "duplicate",
        "url": "https://example.com",
    })
    captured = capsys.readouterr()
    assert "Duplicate" in captured.out


def test_summarize_aborted_status(app, capsys):
    app._summarize_reactive_result({"status": "aborted"})
    captured = capsys.readouterr()
    assert "Aborted" in captured.out
