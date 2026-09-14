# Bundled third-party licence texts

These files accompany JuaDex source and binary distributions. They are not the
licence for JuaDex's original code; that is the MIT licence in `../LICENSE`.

| File | Applies to |
|---|---|
| `AGPL-3.0.txt` | PyMuPDF and its bundled MuPDF engine (AGPL option selected for public builds) |
| `GPL-3.0.txt` and `LGPL-3.0.txt` | Qt 6, PySide6-Essentials and shiboken6 (LGPL option selected) |
| `Apache-2.0.txt` | zxing-cpp |
| `Lucide-ISC.txt` | Lucide/Feather-derived icon geometry in the UI |
| `CPython-3.12.txt` | CPython runtime bundled in Windows builds |
| `NumPy-BSD-3-Clause.txt` | NumPy and its vendored components |
| `Pillow-MIT-CMU.txt` | Pillow and its vendored components |
| `PyInstaller-GPL-2.0-bootloader-exception.txt` | PyInstaller build tool and bootloader exception |

`packaging/collect_licenses.py` validates that complete texts are present and
records the exact installed distributions before an official build. Do not
replace these files with one-line package metadata.

Licences and notices can change between dependency releases. Regenerate and
review this directory whenever `packaging/requirements-release.txt` changes.
