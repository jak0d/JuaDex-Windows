# Third-party notices

JuaDex PDFs Separator is distributed with the third-party components listed
below. Each component remains under its own licence. Full licence texts are
installed alongside the application in the `LICENSES/` folder and are also
available from each project's homepage.

> **Read the "Licensing consequences" section before distributing a build.**
> Two dependencies (PyMuPDF and Qt/PySide6) impose obligations that affect how
> this application may be shipped.

---

## Components

| Component | Version pinned | Licence | Used for |
|---|---|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) | >=1.24,<2 | **AGPL-3.0-or-later**, or a commercial licence from Artifex | Reading, rendering and writing PDF files |
| [MuPDF](https://mupdf.com/) (bundled inside PyMuPDF) | matches PyMuPDF | **AGPL-3.0-or-later**, or a commercial licence from Artifex | PDF engine |
| [PySide6-Essentials](https://doc.qt.io/qtforpython/) / Qt 6 | >=6.7,<7 | **LGPL-3.0** (Qt may alternatively be used under a commercial licence) | Desktop user interface |
| [zxing-cpp](https://github.com/zxing-cpp/zxing-cpp) | >=2.2,<3 | **Apache-2.0** | Barcode decoding and Code 128 generation |
| [NumPy](https://numpy.org/) | >=1.26,<3 | BSD-3-Clause (with 0BSD, MIT, Zlib and CC0-1.0 components) | Image array processing |
| [Pillow](https://python-pillow.org/) | >=10.3 | MIT-CMU | Image helpers and icon generation |
| [CPython](https://www.python.org/) | 3.12 | PSF License Agreement | Language runtime bundled by PyInstaller |
| [PyInstaller](https://pyinstaller.org/) | >=6.6 (build only) | GPL-2.0-or-later **with a bootloader exception** that permits shipping proprietary applications | Packaging |
| [Inno Setup](https://jrsoftware.org/isinfo.php) | 6.x (build only) | Inno Setup licence (free, permits commercial installers) | Windows installer |

The application's own source code is available under the MIT licence; see
`LICENSE`.

---

## Apache-2.0 notice for zxing-cpp

```
Copyright 2016 ZXing authors
Copyright 2022 Axel Waggershauser

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

zxing-cpp is used unmodified. The Apache-2.0 licence text is included in
`LICENSES/Apache-2.0.txt`.

---

## Licensing consequences before you distribute

These points are engineering facts about the chosen stack, not legal advice.
Obtain your own legal review before shipping a build outside your organisation.

### 1. PyMuPDF / MuPDF is AGPL-3.0, not a permissive licence

The PRD's recommended stack specifies PyMuPDF. Artifex dual-licenses it under
**AGPL-3.0-or-later** or a paid commercial licence. Practical consequences:

* **Internal use inside one organisation** — distributing the installer to
  employees of the same legal entity is generally not "distribution to the
  public", and this is the intended deployment for this product.
* **Distributing the application outside your organisation** under AGPL means
  you must offer the *complete corresponding source code* of the whole
  application, under a licence compatible with AGPL-3.0. That would override
  the MIT licence on this project's own code for the combined work.
* **Shipping a closed-source or commercially licensed product** requires a
  commercial PyMuPDF licence from Artifex.

If AGPL is unacceptable and a commercial licence is not an option, the PDF
engine is the component to replace: the processing core isolates all PDF I/O in
`core/analyzer.py`, `core/exporter.py` and `core/separator_pdf.py`.

### 2. Qt / PySide6 is LGPL-3.0

The build satisfies the LGPL by **dynamic linking**: the PyInstaller one-folder
build keeps the Qt DLLs as separate files that the user can replace with their
own compatible Qt build. To keep that property:

* keep using the one-folder build (`dist/JuaDex PDFs Separator/`) for the
  installer and the portable ZIP;
* do not statically link Qt;
* ship this notice and the LGPL-3.0 text with the application;
* state that Qt is used under LGPL-3.0 and that its source is available from
  <https://download.qt.io/>.

The one-file PyInstaller mode (`ONEFILE=1`) is provided for convenience during
testing only; it is not the recommended distribution format for this reason.

### 3. PyInstaller

PyInstaller is GPL-2.0-or-later, but its bootloader carries an exception that
explicitly allows packaging applications of any licence. Using PyInstaller does
not impose the GPL on this application.

---

## Verifying the notices

`packaging/collect_licenses.py` regenerates `LICENSES/` from the installed
distributions, so the shipped texts always match the pinned versions:

```bash
python packaging/collect_licenses.py
```
