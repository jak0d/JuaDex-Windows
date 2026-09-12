"""PRD section 13 acceptance measurement harness.

This is a measurement script, not a test.  It builds a synthetic corpus and
prints the numbers quoted in ``docs/ACCEPTANCE.md`` so the figures in that
document can be reproduced on demand:

    PYTHONPATH=src:tests python tests/acceptance_corpus.py

The regression tests in ``tests/`` are the enforcement mechanism; this script
exists so the acceptance percentages can be re-measured after any change to
the decoding ladder or the blank-page profiles.
"""

from __future__ import annotations

import hashlib
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from fixtures.builders import (
    add_blank_page,
    add_dark_page,
    add_faint_text_page,
    add_other_barcode_page,
    add_separator_page,
    add_text_page,
    build_pdf,
    degrade_pdf_like_scan,
)

from pdf_batch_separator.core.analyzer import (
    analyze_document,
    open_document,
    render_page_array,
)
from pdf_batch_separator.core.barcode import decode_page_barcodes
from pdf_batch_separator.core.batch import AnalysisSettings, analyze_batch, export_batch
from pdf_batch_separator.core.models import BlankSensitivity

SEP = "EAGC-EDMS-00001"


def _rule(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def separator_detection(tmp: Path) -> tuple[int, int]:
    """Separator sheets as they realistically arrive from a scanner."""

    _rule("1. Separator detection - realistic sheets")
    cases: list[dict] = []
    # A separator sheet is printed at full page size; the realistic variation
    # is feed rotation, toner density and scanner contrast.
    for rotation in (0, 90, 180, 270):
        cases.append({"rotation": rotation})
    for contrast in (0.9, 0.75, 0.6, 0.45):
        cases.append({"contrast": contrast})
        cases.append({"contrast": contrast, "rotation": 180})
    for scale in (1.0, 0.9, 0.75, 0.6):
        cases.append({"scale": scale})
        cases.append({"scale": scale, "rotation": 90})
    cases.append({"inverted": True})
    cases.append({"inverted": True, "rotation": 270})

    hits = 0
    for index, kwargs in enumerate(cases):
        path = build_pdf(
            tmp / f"sep{index}.pdf",
            lambda d, kw=kwargs: add_separator_page(d, SEP, **kw),
        )
        document = open_document(path)
        image = render_page_array(document.load_page(0))
        document.close()
        if decode_page_barcodes(image, SEP).matched:
            hits += 1
        else:
            print(f"   MISS {kwargs}")
    print(f"   detected {hits}/{len(cases)} = {100 * hits / len(cases):.1f}%")
    return hits, len(cases)


def degraded_detection(tmp: Path) -> tuple[int, int]:
    """Full print -> scan round trip at realistic office scanner settings."""

    _rule("2. Separator detection - print/scan degraded")
    hits = total = 0
    for index, kwargs in enumerate(
        [{}, {"rotation": 180}, {"contrast": 0.7}, {"scale": 0.9}, {"rotation": 90}]
    ):
        source = build_pdf(
            tmp / f"deg_src{index}.pdf",
            lambda d, kw=kwargs: (
                add_text_page(d, "Document A"),
                add_separator_page(d, SEP, **kw),
                add_text_page(d, "Document B"),
            ),
        )
        for dpi, noise in ((200, 10), (200, 25), (150, 18), (300, 14)):
            out = degrade_pdf_like_scan(
                source, tmp / f"deg{index}_{dpi}_{noise}.pdf", dpi=dpi, noise=noise, seed=noise
            )
            total += 1
            if analyze_document(out, expected_separator=SEP).separator_pages == (1,):
                hits += 1
            else:
                print(f"   MISS {kwargs} dpi={dpi} noise={noise}")
    print(f"   detected {hits}/{total} = {100 * hits / total:.1f}%")
    return hits, total


def false_blank_removals(tmp: Path) -> int:
    """No page carrying real content may ever be dropped."""

    _rule("3. False blank removals")
    pages = {
        "normal_text": lambda d: add_text_page(d, "Employment contract"),
        "one_word": lambda d: add_text_page(d, "Approved", paragraphs=0),
        "faint_pencil": add_faint_text_page,
        "dark_photo": add_dark_page,
        "separator": lambda d: add_separator_page(d, SEP),
        "other_barcode": lambda d: add_other_barcode_page(d, "INV-2026-0042"),
    }
    bad = 0
    for name, builder in pages.items():
        path = build_pdf(tmp / f"nb_{name}.pdf", builder)
        for sensitivity in BlankSensitivity:
            analysis = analyze_document(
                path,
                expected_separator=SEP,
                remove_blanks=True,
                blank_sensitivity=sensitivity,
            )
            if analysis.blank_pages:
                bad += 1
                print(f"   FALSE POSITIVE {name} at {sensitivity.value}")
    print(f"   {len(pages)} page types x {len(list(BlankSensitivity))} profiles -> {bad} removals")
    return bad


def blank_recall(tmp: Path) -> tuple[int, int]:
    """Genuinely blank scanner pages should be caught at the default profile."""

    _rule("4. Blank detection recall (Balanced)")
    hits = total = 0
    for index in range(6):
        path = build_pdf(
            tmp / f"blank{index}.pdf",
            lambda d: (add_text_page(d, "Front"), add_blank_page(d)),
        )
        scanned = degrade_pdf_like_scan(
            path, tmp / f"blank_scan{index}.pdf", dpi=200, noise=6 + index * 4, seed=index
        )
        analysis = analyze_document(scanned, expected_separator=SEP, remove_blanks=True)
        total += 1
        if 1 in analysis.blank_pages:
            hits += 1
        else:
            print(f"   missed blank at noise={6 + index * 4}")
    print(f"   detected {hits}/{total}")
    return hits, total


def performance(tmp: Path) -> tuple[float, float]:
    """Throughput and time-to-first-status on a 100 page document."""

    _rule("5. Performance (100 pages, 300 DPI)")

    def hundred(document) -> None:
        for i in range(100):
            if i % 10 == 9:
                add_separator_page(document, SEP)
            else:
                add_text_page(document, f"Page {i + 1}")

    path = build_pdf(tmp / "hundred.pdf", hundred)
    first: list[float] = []
    start = time.perf_counter()

    def progress(done: int, total: int) -> None:
        if done == 1 and not first:
            first.append(time.perf_counter() - start)

    analysis = analyze_document(path, expected_separator=SEP, progress=progress)
    elapsed = time.perf_counter() - start
    print(f"   total {elapsed:.1f}s ({elapsed / 100 * 1000:.0f} ms/page)")
    print(f"   first page status {first[0]:.2f}s (target < 2s)")
    print(f"   groups={len(analysis.output_groups)} separators={len(analysis.separator_pages)}")
    return elapsed, first[0]


def source_integrity(tmp: Path) -> bool:
    """Sources must be byte identical and untouched after a full batch."""

    _rule("6. Source integrity")
    sources = []
    for index in range(4):
        sources.append(
            build_pdf(
                tmp / f"int{index}.pdf",
                lambda d: (
                    add_text_page(d, "A"),
                    add_separator_page(d, SEP),
                    add_blank_page(d),
                    add_text_page(d, "B"),
                ),
            )
        )
    before = {
        p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in sources
    }
    out = tmp / "integrity_out"
    out.mkdir()
    settings = AnalysisSettings(expected_separator=SEP, remove_blanks=True)
    export_batch(analyze_batch(sources, settings), out)
    after = {
        p: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in sources
    }
    ok = before == after
    print(f"   {len(sources)} sources unchanged (sha256 + mtime): {ok}")
    return ok


def stress_variants(tmp: Path) -> tuple[int, int]:
    """Deliberately abusive inputs, recorded separately from the headline rate."""

    _rule("7. Stress variants (beyond realistic scanning)")
    cases = []
    for scale in (0.45, 0.3, 0.22):
        for rotation in (0, 90, 180, 270):
            cases.append({"scale": scale, "rotation": rotation})
    for contrast in (0.35, 0.28):
        cases.append({"contrast": contrast})
    hits = 0
    for index, kwargs in enumerate(cases):
        path = build_pdf(
            tmp / f"stress{index}.pdf",
            lambda d, kw=kwargs: add_separator_page(d, SEP, **kw),
        )
        document = open_document(path)
        image = render_page_array(document.load_page(0))
        document.close()
        if decode_page_barcodes(image, SEP).matched:
            hits += 1
        else:
            print(f"   miss {kwargs}")
    print(f"   detected {hits}/{len(cases)} = {100 * hits / len(cases):.1f}%")
    return hits, len(cases)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="pbs-acceptance-"))
    try:
        print(f"corpus workspace: {tmp}")
        clean_hits, clean_total = separator_detection(tmp)
        deg_hits, deg_total = degraded_detection(tmp)
        false_pos = false_blank_removals(tmp)
        recall_hits, recall_total = blank_recall(tmp)
        elapsed, first = performance(tmp)
        integrity = source_integrity(tmp)
        stress_hits, stress_total = stress_variants(tmp)

        total_hits = clean_hits + deg_hits
        total_cases = clean_total + deg_total
        _rule("Summary")
        print(f"   separator detection (realistic): {total_hits}/{total_cases} "
              f"= {100 * total_hits / total_cases:.1f}%  (target >= 99%)")
        print(f"   separator detection (stress):    {stress_hits}/{stress_total} "
              f"= {100 * stress_hits / stress_total:.1f}%  (no target)")
        print(f"   false blank removals:            {false_pos}  (target 0)")
        print(f"   blank recall:                    {recall_hits}/{recall_total}")
        print(f"   100-page analysis:               {elapsed:.1f}s "
              f"({elapsed / 100 * 1000:.0f} ms/page)")
        print(f"   first-page status:               {first:.2f}s  (target < 2s)")
        print(f"   sources unchanged:               {integrity}  (required)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
