# Public source and Windows binary release checklist

A release owner must complete and record every applicable item. Do not make the
repository or an attached binary public while a **BLOCKER** remains.

## Rights and privacy

- [ ] **BLOCKER:** jak0d has completed the confirmation in `docs/PROVENANCE.md`.
- [ ] New commits have DCO sign-offs or equivalent documented provenance.
- [ ] Third-party snippets/assets have source, copyright, licence and notices recorded.
- [ ] Screenshots, fixtures, logs and metadata contain no personal/confidential data.
- [ ] Full reachable Git history has been rescanned for credentials and sensitive files.

## Dependencies and corresponding source

- [ ] Release uses only exact versions in `packaging/requirements-release.txt`.
- [ ] `pip check` and a vulnerability scan (for example `pip-audit`) pass, or each
      accepted finding has a documented risk decision.
- [ ] `python packaging/collect_licenses.py` passes in the actual CPython 3.12
      Windows build environment and generated inventory/notices are reviewed.
- [ ] Every packaged component appears in `THIRD_PARTY_NOTICES.md`; every required
      full licence/notice is present in `LICENSES/` and in the installed/portable build.
- [ ] **BLOCKER:** the GitHub release provides equivalent access to the complete,
      exact corresponding source required by AGPL-3.0, including the tagged JuaDex
      source/build scripts and applicable PyMuPDF/MuPDF source. Preserve it for as
      long as the binaries are offered. Obtain legal review if the chosen section 6
      distribution method is uncertain.
- [ ] Qt/PySide6/shiboken6 source availability is recorded; GPL-3.0 and LGPL-3.0
      texts and required installation/relinking information accompany the binary.

## Build and test

- [ ] Build comes from a clean checkout of the public release tag on 64-bit Windows
      with Python 3.12 by running `packaging/build_windows.ps1`.
- [ ] Full tests pass and the packaged-app smoke test passes.
- [ ] Build is one-folder only; Qt DLLs remain separate and replaceable. No one-file
      executable or static Qt build is distributed.
- [ ] Installer and portable archive were inspected to confirm no `.env`, signing
      material, local paths, test data, caches or unrelated files were included.
- [ ] Offline/network tests and privacy claims still match actual behavior.

## Authenticity and publication

- [ ] Executable and installer are signed with a trusted publisher certificate;
      certificate/private-key material is never committed or uploaded as an artifact.
- [ ] SHA-256 sums are generated after signing and independently verified.
- [ ] Release notes identify exact commit/tag, dependency/legal terms, source links,
      checksums, signing status and known security limitations.
- [ ] GitHub private vulnerability reporting, secret scanning, dependency graph,
      Dependabot alerts and branch protection are enabled after visibility changes.
- [ ] A clean-machine install/uninstall and portable run have been tested.
- [ ] Existing noncompliant or unverifiable release assets are replaced or kept
      non-public; publishing new notices does not retroactively fix old archives.

## Current 1.0.0 release blocker

The pre-audit `v1.0.0` release contains two binary assets built before complete
licence texts were bundled and before exact corresponding-source publication was
verified. **Do not make that release public as-is.** Rebuild and replace it after
this checklist passes, or remove its assets before changing repository visibility.
