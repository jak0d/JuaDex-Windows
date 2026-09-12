"""Proves the privacy claim: processing performs no network activity.

PRD acceptance criterion 14 ("Runtime processing performs no network calls and
the app contains no telemetry").  Sockets are poisoned for the duration of a
real analyse-and-export run, so any outbound connection fails the test.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from fixtures.builders import add_blank_page, add_separator_page, add_text_page, build_pdf
from pdf_batch_separator.core.analyzer import analyze_document
from pdf_batch_separator.core.exporter import export_document
from pdf_batch_separator.core.models import ProcessingMode
from pdf_batch_separator.core.separator_pdf import create_separator_pdf

SEP = "EAGC-EDMS-00001"


class NetworkAccessAttempted(AssertionError):
    """Raised when code under test tries to reach the network."""


@pytest.fixture
def no_network(monkeypatch):
    """Make every outbound network operation fail loudly."""

    def blocked(*args, **kwargs):
        raise NetworkAccessAttempted(
            "The application attempted a network operation during processing."
        )

    # Block at both the connection layer and the name-resolution layer.
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket, "gethostbyname", blocked)
    return blocked


@pytest.fixture
def sample_pdf(workdir):
    def build(doc):
        add_text_page(doc, "Alpha")
        add_separator_page(doc, SEP)
        add_text_page(doc, "Beta")
        add_blank_page(doc)

    return build_pdf(workdir / "batch.pdf", build)


def test_analysis_makes_no_network_calls(no_network, sample_pdf):
    analysis = analyze_document(sample_pdf, expected_separator=SEP, remove_blanks=True)
    assert analysis.error is None
    assert analysis.separator_pages == (1,)


def test_export_makes_no_network_calls(no_network, sample_pdf, outdir):
    analysis = analyze_document(sample_pdf, expected_separator=SEP, remove_blanks=True)
    result = export_document(analysis, outdir)
    assert result.succeeded
    assert len(result.outputs) == 2


def test_blank_cleanup_makes_no_network_calls(no_network, sample_pdf, outdir):
    analysis = analyze_document(sample_pdf, mode=ProcessingMode.CLEAN_ONLY)
    result = export_document(analysis, outdir)
    assert result.succeeded


def test_separator_generation_makes_no_network_calls(no_network, workdir):
    created = create_separator_pdf(SEP, workdir / "sheet.pdf")
    assert created.exists()


def test_source_has_no_network_imports():
    """Static check: the shipped package must not import networking modules."""

    import pdf_batch_separator

    package_root = Path(pdf_batch_separator.__file__).parent
    forbidden = (
        "import requests",
        "import urllib.request",
        "from urllib.request",
        "import http.client",
        "from http.client",
        "import socket",
        "import ftplib",
        "import telnetlib",
        "import smtplib",
        "webbrowser",
        "QNetworkAccessManager",
        "QTcpSocket",
        "QUdpSocket",
        "QTcpServer",
    )

    offenders: list[str] = []
    for source in package_root.rglob("*.py"):
        text = source.read_text(encoding="utf-8")
        for needle in forbidden:
            if needle in text:
                offenders.append(f"{source.relative_to(package_root)}: {needle}")

    assert not offenders, "networking code found in the shipped package: " + "; ".join(
        offenders
    )


def test_no_telemetry_markers_in_source():
    """No analytics or crash-reporting SDK may be referenced."""

    import pdf_batch_separator

    package_root = Path(pdf_batch_separator.__file__).parent
    markers = (
        "sentry",
        "analytics",
        "telemetry",
        "mixpanel",
        "amplitude",
        "google-analytics",
        "posthog",
        "bugsnag",
    )

    offenders: list[str] = []
    for source in package_root.rglob("*.py"):
        lowered = source.read_text(encoding="utf-8").lower()
        for marker in markers:
            # "telemetry" legitimately appears in user-facing privacy wording.
            if marker in lowered and marker != "telemetry":
                offenders.append(f"{source.relative_to(package_root)}: {marker}")

    assert not offenders, "telemetry references found: " + "; ".join(offenders)
