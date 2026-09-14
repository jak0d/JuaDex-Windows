# Third-party notices

JuaDex PDFs Separator uses the components below. Each remains under its own
licence. Complete selected licence texts are in `LICENSES/` and are shipped
with official binaries. This notice does not replace those terms.

> **Binary releases are not MIT-only.** The original JuaDex code is offered
> under MIT, but an official binary combines it with AGPL- and LGPL-covered
> components. Read the distribution requirements below before publishing or
> mirroring a build. This document is compliance guidance, not legal advice.

## Runtime and packaged components

| Component | Official release pin | Selected licence | Purpose / text |
|---|---:|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) and bundled [MuPDF](https://mupdf.com/) | 1.28.2 | **AGPL-3.0** (commercial licensing is also available from Artifex) | PDF engine — `LICENSES/AGPL-3.0.txt` |
| [PySide6-Essentials](https://doc.qt.io/qtforpython/), shiboken6 and Qt 6 | 6.11.2 | **LGPL-3.0-only** option | GUI — `LICENSES/LGPL-3.0.txt` and `LICENSES/GPL-3.0.txt` |
| [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp) | 2.3.0 | Apache-2.0 | Barcodes — `LICENSES/Apache-2.0.txt` |
| [NumPy](https://numpy.org/) | 2.4.6 | BSD-3-Clause plus licences for vendored components | Image arrays — `LICENSES/NumPy-BSD-3-Clause.txt` |
| [Pillow](https://python-pillow.org/) | 12.3.0 | MIT-CMU plus licences for vendored components | Images/icons — `LICENSES/Pillow-MIT-CMU.txt` |
| [CPython](https://www.python.org/) | 3.12 | PSF-2.0 and incorporated-component licences | Runtime — `LICENSES/CPython-3.12.txt` |
| [Lucide](https://lucide.dev/) / Feather-derived icon geometry | current geometry adapted in source | ISC and MIT | UI icons — `LICENSES/Lucide-ISC.txt` |

The icon path data in `src/pdf_batch_separator/ui/icons.py` follows and adapts
Lucide geometry. Lucide's notice, including the notice for Feather-derived
icons, is preserved in `LICENSES/Lucide-ISC.txt`.

### zxing-cpp attribution

Copyright 2016 ZXing authors

Copyright 2022 Axel Waggershauser

Licensed under the Apache License, Version 2.0. zxing-cpp is used unmodified.
The complete terms are in `LICENSES/Apache-2.0.txt`.

## Build and installer components

| Component | Official release pin | Licence | Notes / text |
|---|---:|---|---|
| [PyInstaller](https://pyinstaller.org/) | 6.22.3 | GPL-2.0-or-later with bootloader exception | The exception permits distributing the packaged application — `LICENSES/PyInstaller-GPL-2.0-bootloader-exception.txt` |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | 6.x | Inno Setup licence | Used to create the Windows installer; not installed as part of JuaDex |

Exact official-build pins are maintained in
`packaging/requirements-release.txt`. Wheel-supplied notices and the installed
version inventory are generated during the release build by
`packaging/collect_licenses.py`.

## Requirements for distributing binaries

### PyMuPDF / MuPDF (AGPL-3.0)

The public binary uses the AGPL option, not a commercial Artifex licence. A
person conveying that binary must comply with AGPL-3.0, including providing the
complete corresponding source through a method allowed by section 6. For an
official GitHub release, publish the exact tagged JuaDex source and build
scripts together with access to the corresponding source for PyMuPDF/MuPDF and
other covered components. Preserve notices and state significant modifications.

The MIT licence continues to apply to JuaDex's original files; it does not
remove obligations that apply to the combined binary. Do not describe an
official executable as “MIT licensed” without this qualification. A distributor
that does not want to satisfy AGPL must obtain an appropriate commercial
licence from Artifex or replace this dependency before building.

### Qt / PySide6 / shiboken6 (LGPL-3.0)

Official releases use the LGPL option. Keep Qt libraries dynamically linked and
as separate, replaceable files in the PyInstaller **one-folder** layout. Do not
publish a one-file or statically linked build. Ship the GPL-3.0 and LGPL-3.0
texts, permit reverse engineering for debugging modifications, and provide the
corresponding application code and installation information required by LGPL
section 4. Qt source is available from <https://download.qt.io/>.

### Other components

Preserve the Apache, BSD, MIT-CMU, ISC/MIT, PSF and PyInstaller notices included
in `LICENSES/`. The complete NumPy, Pillow and CPython files contain notices for
components incorporated in those distributions and must be shipped intact.

## Release verification

Before publishing any installer or portable archive:

```powershell
python -m pip install -r packaging\requirements-release.txt
python -m pip install -e . --no-deps
python packaging\collect_licenses.py
python -m pytest -q
```

Then follow every item in `docs/RELEASE_CHECKLIST.md`. If the dependency set or
packaged file inventory changes, repeat the licence review rather than assuming
this notice is still complete.
