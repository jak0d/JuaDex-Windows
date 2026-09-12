# Privacy statement

**Your PDFs are processed only on this PC.**

PDF Batch Separator is an offline desktop application. It is designed so that
document content never leaves the computer it runs on.

## What the application does

* Reads the PDF files you add to the list.
* Renders their pages in memory to look for barcode separator sheets and blank
  pages.
* Writes new PDF files into the output folder you choose.
* Writes a plain-text batch report into that same output folder.

## What the application does **not** do

* **No internet access.** The application makes no network requests of any
  kind: no update checks, no licence checks, no cloud processing, no fonts or
  content loaded from the internet.
* **No telemetry or analytics.** Nothing about you, your files or your usage is
  collected, measured or transmitted.
* **No accounts.** There is no sign-in, no licence server and no subscription.
* **No local web server.** The application does not open any listening port.
* **No cloud or SharePoint integration.** OneDrive-synced folders work only
  because Windows presents them as ordinary local folders.
* **No AI, OCR or text extraction.** Page *content* is never interpreted; only
  barcode symbols and the amount of ink on a page are measured.

## What is stored on your computer

| Item | Location | Contents |
|---|---|---|
| Preferences | Windows registry, under `HKCU\Software\PDF Batch Separator` | Last output folder, separator value, blank-page sensitivity, subfolder and theme preferences |
| Diagnostic log | `%LOCALAPPDATA%\PDF Batch Separator\logs\` | Timestamps, operation names and error messages. **No page content, no barcode payloads from your documents, no metadata.** Rotates at 1 MB, keeps 2 previous files. |
| Batch report | The output folder you chose | File names, page numbers, counts and status messages. **No page content.** |
| Temporary files | Inside the output folder while writing | Partially written PDFs with unpredictable names, deleted as soon as the file is finished, on error, and on the next launch after a crash. |

The application does **not** keep a history of the documents you processed.

## Your source files

Source PDFs are opened read-only. They are never modified, moved, renamed or
deleted. Existing files in the output folder are never overwritten: if a name
is already taken, a new file is created with ` (2)`, ` (3)` and so on appended.

## Digital signatures

Exported documents are rebuilt page by page. If a source PDF carries a digital
signature, that signature will **not** remain valid in the exported files. The
application warns you before processing when it detects a signature.

## Verifying these claims

The application is open source. The claims above can be checked directly:

* Network isolation is verified by the automated test
  `tests/test_no_network.py`, which fails the build if any socket connection is
  attempted during analysis or export.
* Report contents are verified by `TestReport::test_report_has_no_page_content`.
* Source preservation is verified by
  `TestExportDocument::test_source_is_unchanged`, which compares SHA-256
  digests before and after processing.

You can also confirm offline behaviour yourself by disconnecting the machine
from all networks: every feature continues to work.
