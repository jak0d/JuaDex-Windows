"""Batch scheduler behaviour."""

from __future__ import annotations

import threading
from pathlib import Path

from pdf_batch_separator.core.batch import AnalysisSettings, analyze_batch
from pdf_batch_separator.core.models import DocumentAnalysis


def test_analysis_results_stream_as_each_file_finishes(monkeypatch, tmp_path):
    """A fast file should not wait behind a slow earlier file in the UI."""

    slow_can_finish = threading.Event()
    slow = tmp_path / "slow.pdf"
    fast = tmp_path / "fast.pdf"
    slow.write_bytes(b"%PDF slow")
    fast.write_bytes(b"%PDF fast")

    def fake_analyze(path: Path, **_kwargs) -> DocumentAnalysis:
        if path == slow:
            slow_can_finish.wait(timeout=2.0)
        return DocumentAnalysis(source_path=path, page_count=1)

    observed: list[int] = []

    def on_result(index: int, _analysis: DocumentAnalysis) -> None:
        observed.append(index)
        if index == 1:
            slow_can_finish.set()

    monkeypatch.setattr("pdf_batch_separator.core.batch.analyze_document", fake_analyze)

    results = analyze_batch(
        [slow, fast],
        AnalysisSettings(),
        on_result=on_result,
        max_workers=2,
    )

    assert observed[0] == 1
    assert [result.source_path for result in results] == [slow, fast]
