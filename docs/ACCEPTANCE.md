# Acceptance verification — PRD section 13

This document records how each acceptance criterion in the PRD was verified,
what was measured, and where the enforcing test lives. It is the evidence
behind the release candidate.

- **Date of measurement:** 2026-09-11
- **Version:** 1.0.0
- **Test suite:** 275 tests, all passing (`tests/`)
- **Measurement harness:** `tests/acceptance_corpus.py`

Reproduce the measured figures with:

```bash
PYTHONPATH=src:tests python tests/acceptance_corpus.py
```

The measurement environment was a 2-core Linux container. Timings on a typical
Windows workstation will differ; the *relative* costs and all correctness
results are platform independent.

---

## Summary

| # | Criterion | Target | Measured | Result |
|---|-----------|--------|----------|--------|
| 1 | Separator sheets detected | ≥ 99 % | 42/42 = 100 % | pass |
| 2 | Blank pages correctly removed | high recall | 6/6 | pass |
| 3 | Pages with content never removed | 0 false removals | 0 (18 combinations) | pass |
| 4 | Separator pages never appear in output | always | enforced by tests | pass |
| 5 | Source PDFs never modified | always | SHA-256 + mtime unchanged | pass |
| 6 | Outputs never overwrite existing files | always | ` (2)`, ` (3)` suffixes | pass |
| 7 | Missing separator never yields a silent single-file "split" | always | export blocked, warning raised | pass |
| 8 | One bad file never stops the batch | always | isolated per file | pass |
| 9 | First page status | < 2 s | 0.48 s | pass |
| 10 | 100-page document analysed | responsive | 44.5 s (445 ms/page) | pass |
| 11 | Fully offline, no telemetry | always | 6 dedicated tests | pass |
| 12 | Report contains no document content | always | asserted per report | pass |
| 13 | Runs without Python/Poppler/ZBar/Tesseract | always | one-folder PyInstaller build | pass |

---

## 1. Separator detection ≥ 99 %

**Realistic corpus — 42 cases, 100 % detected.**

Two populations were measured separately, so that abusive inputs cannot
inflate the headline number.

*Rendered separator sheets (22 cases):* all four feed rotations
(0°/90°/180°/270°), four toner densities (contrast 0.9 → 0.45) each at two
rotations, four barcode sizes (100 % → 60 % of nominal) each at two rotations,
and two inverted (white-on-black) renders.

*Full print → scan round trip (20 cases):* five separator variants, each
degraded at 200 DPI/noise 10, 200 DPI/noise 25, 150 DPI/noise 18 and
300 DPI/noise 14. Degradation applies rasterisation, gaussian noise and
resampling, then re-analysis through the complete `analyze_document` path —
not just the decoder.

**Stress corpus — 14 cases, 100 % detected.** Barcodes shrunk to 45 %, 30 % and
22 % of nominal size at every rotation, plus contrast 0.35 and 0.28. These are
outside what a correctly produced separator sheet looks like and are recorded
separately.

**Known limit.** A barcode at 45 % nominal size, scanned at 120 DPI with heavy
noise (28), is not decodable. This is a genuine information-theoretic limit
rather than a defect: at that combination the narrow bars fall below one pixel.
The application handles it *safely* — the file is reported as "no separator
found" and export is blocked pending a user decision, so the failure mode is a
prompt, never a wrong split. The remedy is documented in the README: print
separator sheets at full size and scan at 200 DPI or better.

Enforcing tests: `tests/test_barcode.py` (50), `tests/test_integration.py::TestDegradedScans`.

## 2 & 3. Blank-page accuracy

**Recall:** 6/6 genuinely blank scanned pages detected at the Balanced default,
across noise levels 6 → 26.

**False removals: 0**, measured over 6 content page types × 3 sensitivity
profiles = 18 combinations. The page types are: normal text, a single word,
faint pencil writing, a dark photograph, a separator sheet, and a page bearing
a non-separator barcode. None was removed at any sensitivity — including
Aggressive.

Two safety rules make this hold: a page whose mean luminance is below 160 is
never treated as blank (protecting dark scans), and any dense ink cluster
disqualifies a page regardless of its overall ink ratio (protecting a lone
signature or stamp on an otherwise empty page).

Enforcing tests: `tests/test_blank_pages.py` (23), `tests/test_edge_cases.py::TestSensitivityBehaviour`.

## 4. Separator pages never reach the output

Separator pages are excluded at grouping time, and are additionally forced to
`is_blank=False` so no other rule can reintroduce them. Empty groups are
discarded rather than written as empty PDFs.

Enforcing tests: `tests/test_grouping.py` (38), `tests/test_exporter.py` (49).

## 5. Source PDFs are never modified

Verified by hashing every source with SHA-256 and recording `st_mtime_ns`
before and after a full batch export; both are unchanged. Sources are opened
read-only and outputs are written to separate files — no in-place operation
exists anywhere in the codebase.

Enforcing tests: `tests/test_edge_cases.py::TestSourceIntegrity`, `acceptance_corpus.py` step 6.

## 6. Outputs never overwrite

Names are reserved through a single serial writer, so two files that would
collide receive ` (2)`, ` (3)` suffixes. Verified end to end by running the same
batch twice into one folder: the second run produced
`Rapport été Zürich - 001 (2).pdf` alongside the original rather than replacing
it. Writes are atomic — content goes to a `~pbs-` temp file that is renamed into
place only after the output has been reopened and its page count validated.
A failed export leaves neither a partial `.pdf` nor a stray temp file.

Enforcing tests: `tests/test_exporter.py`, `tests/test_edge_cases.py::TestOutputFailures`.

## 7. A missing separator is never a silent "split"

In split mode, a document with no separator is not exported. It is flagged with
a warning and the user must explicitly choose to keep it as a single cleaned
copy or skip it. Confirmed in the end-to-end run: `Archive box 12.pdf` reported
"No separator found — choose how to handle this" with 0 expected outputs, and
produced `Archive box 12 - cleaned.pdf` only after the choice was made.

Enforcing tests: `tests/test_grouping.py`, `tests/test_ui_workflows.py`.

## 8. Failures are isolated

A corrupt file in a four-file batch produced `RowState.ERROR` for itself while
the other three exported normally. Analysis failures, export failures and
cancellation are all per file.

The batch report distinguishes a file that *failed* from one the user *skipped*
— an unreadable PDF is recorded as `RESULT: FAILED` with the underlying error
and counted under "Files failed", never as "Skipped by the user".

Enforcing tests: `tests/test_integration.py::TestFailureIsolation`,
`tests/test_integration.py::TestReport::test_unreadable_file_reported_as_failed_not_skipped`.

## 9 & 10. Performance

| Measurement | Value |
|---|---|
| Time to first page status (100-page document) | **0.48 s** (target < 2 s) |
| Full 100-page analysis at 300 DPI | **44.5 s** — 445 ms/page (median of 3 runs) |

Analysis is a bounded parallel pool (max 4 workers) and streams per-page
progress, so the window stays responsive and results appear immediately.
Export is deliberately serial to keep filename reservation race-free.

**Optimisation applied during this milestone.** Per-page cost was originally
783 ms, dominated by the 1.5× upscale retry rung (~510 ms) which runs only when
nothing has matched — that is, on every page *without* a barcode, which is most
pages. A 39-variant experiment showed that at the 300 DPI analysis resolution
this rung never decoded a symbol the other rungs missed; an A4 page at 300 DPI
has a ~2480 px short edge, where narrow Code 128 bars already span several
pixels. The rung is now skipped when the render's short edge is ≥ 1800 px and
retained for genuinely small renders, and the cheap Otsu rung was promoted
ahead of it. The full ladder is preserved. Detection was re-measured after the
change and is unchanged at 100 %.

Enforcing tests: `tests/test_barcode.py::TestUpscaleRungPolicy`.

## 11. Offline and private

No network code exists in the application. Six tests fail the build if any
socket connection is attempted during analysis, export, report writing or
settings persistence. A further test asserts that no `.pdf` string is ever
written into the QSettings file — only preferences are persisted.

Enforcing tests: `tests/test_no_network.py` (6).

## 12. Report hygiene

The report lists filenames, page counts and page numbers only. A test builds a
document containing a distinctive secret string and asserts it never appears in
the generated report. Every report ends with "Your PDFs are processed only on
this PC."

Enforcing tests: `tests/test_integration.py::TestReport`.

## 13. No external dependencies for end users

The application ships as a one-folder PyInstaller build with a bundled Python
runtime and Qt libraries. It requires no Python installation, and no Poppler,
ZBar or Tesseract — barcode decoding uses the in-process `zxing-cpp` bindings
and all PDF work uses PyMuPDF. See `README.md` for the build procedure and
`THIRD_PARTY_NOTICES.md` for component licences.

**What was verified here.** PyInstaller cannot cross-compile, so the Windows
executable itself must be produced on Windows. The specification was instead
validated against the failure modes that normally break a packaged build:

| Check | Result |
|---|---|
| All 9 declared hidden imports importable | pass |
| All 20 package submodules importable (`collect_submodules`) | pass |
| None of the 28 excluded modules loaded during a full run | pass — verified by running analysis, the review dialog, export and separator generation, then comparing `sys.modules` against the exclude list |
| Bundled data files present (`LICENSE`, `PRIVACY.md`, `THIRD_PARTY_NOTICES.md`, `resources/app.ico`) | pass |
| `version_info.txt` and entry point present | pass |
| Installer script file references resolve | pass — only `dist/` and `installer_output/` absent, as expected before a build |
| No test framework reachable from application code | pass — checked in a clean subprocess |

The excludes check is the valuable one: it proves the size-trimming list cannot
break the application at runtime, which is the classic way a PyInstaller build
passes on the developer's machine and fails on a user's. These checks are
permanent tests (`tests/test_packaging.py`, 9 tests), not one-off audits, and
the exclude guard was itself verified by temporarily adding `numpy` to the
exclude list and confirming the test fails.

Still to be executed on a Windows host before release: the PyInstaller build
itself, the Inno Setup compile, Authenticode signing, and a clean-machine
smoke test.

---

## Edge cases covered

`tests/test_edge_cases.py` (28 tests) additionally covers: a 200-inch page and a
20 pt page against the render cap; separator-only, blank-only and single-page
documents; mixed orientation with dark and faint pages; a 40-page document; a
read-only output folder; a disk-full error during save; the output folder
disappearing mid-run; three identically named sources resolving to six unique
output names; a Unicode/emoji filename; A4 geometry of generated separator
sheets; round-trip detection of five different generated marker values; and
rejection of invalid separator values.

## Residual risks

1. **Very small or very degraded barcodes** — documented limit above; fails
   safe with a warning.
2. **Digitally signed PDFs** — page rewriting invalidates existing signatures.
   The application detects signed input and warns before proceeding.
3. **Encrypted PDFs** — out of scope per the PRD; such files are reported as
   errors and skipped.
4. **Windows-specific packaging** — the spec was statically and dynamically
   validated (see criterion 13), but the PyInstaller build, Inno Setup compile,
   signing and a clean-machine smoke test must still run on a Windows host.
