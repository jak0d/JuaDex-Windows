"""Grouping to disk: atomic, non-overwriting PDF export (PRD FR-5).

Writing strategy for every output document:

1. build the new PDF in memory from the retained source pages;
2. save it to a temporary file *in the destination directory* with an
   unpredictable name (same filesystem, so the final rename is atomic);
3. re-open the temporary file and verify it has the expected page count;
4. atomically rename it into place on a name that does not already exist.

If anything fails, the temporary file is removed and no partial output is left
behind.  Source documents are opened read-only and never written to.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable, Sequence
from pathlib import Path

try:
    import pymupdf
except ImportError:  # pragma: no cover
    import fitz as pymupdf  # type: ignore[no-redef]

from .analyzer import open_document
from .grouping import group_pages
from .models import (
    DocumentAnalysis,
    DocumentExportResult,
    ExportedFile,
    PageOverrides,
    PageStatus,
    ProcessingMode,
)
from .naming import cleaned_name, split_name, unique_path

logger = logging.getLogger(__name__)

TEMP_PREFIX = "~pbs-"
"""Prefix for our temp files, so stale-file cleanup only touches our own."""

TEMP_SUFFIX = ".tmp"


class ExportCancelled(Exception):
    """Raised internally when the caller cancels mid-export."""


def _temp_path(directory: Path) -> Path:
    """Unpredictable temp name inside the destination directory."""

    return Path(directory) / f"{TEMP_PREFIX}{secrets.token_hex(8)}{TEMP_SUFFIX}"


def _copy_metadata(source_doc, target_doc) -> None:
    """Copy document metadata when it is safe to do so."""

    try:
        metadata = dict(source_doc.metadata or {})
    except Exception:  # pragma: no cover
        return
    # Drop fields that would misrepresent the derived file.
    for key in ("format", "encryption"):
        metadata.pop(key, None)
    metadata["producer"] = "JuaDex PDFs Separator"
    try:
        target_doc.set_metadata(metadata)
    except Exception:  # pragma: no cover - metadata must never block output
        logger.debug("Could not copy metadata", exc_info=True)


def write_group(
    source_doc,
    page_indexes: Sequence[int],
    destination: Path,
    *,
    reserved: set[Path] | None = None,
) -> ExportedFile:
    """Write one output PDF containing ``page_indexes`` from ``source_doc``.

    ``destination`` is the *desired* final path; the actual path may gain a
    ``' (2)'`` suffix if the name is taken.  Returns the file actually written.
    """

    destination = Path(destination)
    directory = destination.parent
    directory.mkdir(parents=True, exist_ok=True)

    final_path = unique_path(directory, destination.name, reserved=reserved)
    if reserved is not None:
        reserved.add(final_path)

    temp_path = _temp_path(directory)
    target = pymupdf.open()
    try:
        for index in page_indexes:
            # insert_pdf copies the page objects, preserving size, rotation and
            # content streams — no image re-encoding (FR-5).
            target.insert_pdf(source_doc, from_page=index, to_page=index)
        _copy_metadata(source_doc, target)
        target.save(str(temp_path), garbage=4, deflate=True)
    except Exception:
        target.close()
        temp_path.unlink(missing_ok=True)
        raise
    else:
        target.close()

    # --- validate before finalising ---------------------------------
    try:
        verify = pymupdf.open(str(temp_path))
        try:
            actual = verify.page_count
        finally:
            verify.close()
        if actual != len(page_indexes):
            raise OSError(
                f"Validation failed: expected {len(page_indexes)} pages, found {actual}."
            )
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    # --- atomic publish ---------------------------------------------
    try:
        os.replace(temp_path, final_path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise

    return ExportedFile(
        path=final_path,
        page_count=len(page_indexes),
        source_pages=tuple(page_indexes),
    )


def export_document(
    analysis: DocumentAnalysis,
    output_folder: Path,
    *,
    overrides: PageOverrides | None = None,
    reserved: set[Path] | None = None,
    allow_unsplit_copy: bool = False,
    should_cancel: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> DocumentExportResult:
    """Export every output group of one analysed document.

    ``allow_unsplit_copy`` lets the user explicitly accept a file that has no
    separator: it is then exported as a single cleaned document.  Without that
    opt-in, a missing separator is an error, never a silent one-file "split"
    (PRD section 6.3).
    """

    source_path = Path(analysis.source_path)
    output_folder = Path(output_folder)

    if analysis.failed:
        return DocumentExportResult(source_path=source_path, error=analysis.error)

    # Recompute grouping with the live overrides so the UI's preview and the
    # exported result can never diverge.
    grouping = group_pages(
        analysis.pages,
        mode=analysis.mode,
        remove_blanks=analysis.remove_blanks,
        overrides=overrides,
    )
    groups = grouping.groups

    separators_removed = sum(
        1 for status in grouping.statuses if status is PageStatus.SEPARATOR
    )
    blanks_removed = sum(1 for status in grouping.statuses if status is PageStatus.BLANK)

    # An explicit "this detected separator is really content" override is a
    # deliberate no-split instruction. A force-keep on an ordinary blank page
    # is only a blank-page correction and must not bypass the missing-separator
    # safety prompt.
    user_chose_no_split = bool(overrides and overrides.force_not_separator)
    if (
        analysis.mode is ProcessingMode.SPLIT
        and separators_removed == 0
        and not allow_unsplit_copy
        and not user_chose_no_split
    ):
        return DocumentExportResult(
            source_path=source_path,
            skipped=True,
            skip_reason=(
                f"No separator matching “{analysis.expected_separator}” was found. "
                "Choose how to handle this file, then process again."
            ),
        )

    if not groups:
        return DocumentExportResult(
            source_path=source_path,
            skipped=True,
            skip_reason=(
                "Every page would be removed, so no document was written. "
                "Correct a page status or skip this file."
            ),
        )

    warnings: list[str] = []
    if grouping.empty_group_count:
        warnings.append(
            f"{grouping.empty_group_count} empty section(s) from adjacent or edge "
            "separator sheets were ignored."
        )
    if analysis.is_signed:
        warnings.append(
            "The source appeared to be digitally signed; exported documents do not "
            "preserve signature validity."
        )

    outputs: list[ExportedFile] = []
    stem = source_path.stem
    single_document = analysis.mode is ProcessingMode.CLEAN_ONLY or (
        len(groups) == 1 and separators_removed == 0
    )

    try:
        source_doc = open_document(source_path)
    except Exception as exc:  # noqa: BLE001
        return DocumentExportResult(source_path=source_path, error=str(exc))

    try:
        total = len(groups)
        if progress:
            progress(0, total)
        for position, page_indexes in enumerate(groups, start=1):
            if should_cancel and should_cancel():
                raise ExportCancelled()
            name = (
                cleaned_name(stem)
                if single_document
                else split_name(stem, position, total)
            )
            outputs.append(
                write_group(
                    source_doc,
                    page_indexes,
                    output_folder / name,
                    reserved=reserved,
                )
            )
            if progress:
                progress(position, total)
    except ExportCancelled:
        return DocumentExportResult(
            source_path=source_path,
            outputs=tuple(outputs),
            separators_removed=separators_removed,
            blanks_removed=blanks_removed,
            warnings=tuple(warnings),
            skipped=True,
            skip_reason="Cancelled before all documents were written.",
        )
    except Exception as exc:  # noqa: BLE001 - isolate per-document failures
        logger.exception("Export failed for %s", source_path.name)
        return DocumentExportResult(
            source_path=source_path,
            outputs=tuple(outputs),
            separators_removed=separators_removed,
            blanks_removed=blanks_removed,
            warnings=tuple(warnings),
            error=f"Export failed: {exc}",
        )
    finally:
        try:
            source_doc.close()
        except Exception:  # pragma: no cover
            pass

    return DocumentExportResult(
        source_path=source_path,
        outputs=tuple(outputs),
        separators_removed=separators_removed,
        blanks_removed=blanks_removed,
        warnings=tuple(warnings),
    )


def cleanup_stale_temp_files(directory: Path, *, max_age_seconds: float = 0.0) -> int:
    """Delete leftover temp files *created by this app* in ``directory``.

    Only files matching our own prefix/suffix are considered; the system temp
    directory is never broad-deleted (PRD reliability requirements).
    """

    directory = Path(directory)
    if not directory.is_dir():
        return 0
    import time

    removed = 0
    now = time.time()
    for candidate in directory.glob(f"{TEMP_PREFIX}*{TEMP_SUFFIX}"):
        try:
            if not candidate.is_file():
                continue
            if max_age_seconds and (now - candidate.stat().st_mtime) < max_age_seconds:
                continue
            candidate.unlink()
            removed += 1
        except OSError:  # pragma: no cover - locked file
            continue
    return removed


__all__ = [
    "ExportCancelled",
    "TEMP_PREFIX",
    "cleanup_stale_temp_files",
    "export_document",
    "write_group",
]
