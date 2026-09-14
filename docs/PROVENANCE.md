# Copyright and asset provenance review

This record prevents assumptions about authorship from becoming licence claims.
It was prepared before making the repository public.

## Confirmed third-party material

| Material | Location | Treatment |
|---|---|---|
| Lucide/Feather-style icon geometry | `src/pdf_batch_separator/ui/icons.py` | Attributed in `THIRD_PARTY_NOTICES.md`; complete ISC/MIT notice in `LICENSES/Lucide-ISC.txt` |
| Runtime and build dependencies | `pyproject.toml`, `packaging/requirements-release.txt` | Exact release inventory and selected licence texts in `THIRD_PARTY_NOTICES.md` and `LICENSES/` |

No vendored source trees, fonts, stock photographs, real customer PDFs or test
documents were found. Test PDFs are generated in code. The documentation
screenshots show synthetic file names and synthetic document previews.

## Maintainer confirmation required before public release

The maintainer selected “uncertain” when asked whether all original material was
cleared. Automated inspection cannot establish authorship. Before changing
repository visibility or publishing replacement binaries, **jak0d must confirm
in writing (for example, in the release-preparation pull request) that they own
or have MIT-compatible permission for**:

- all Python, test, packaging and documentation content not identified above;
- `src/pdf_batch_separator/resources/app.ico` and the four small SVG controls;
- `docs/screenshot-main.png` and `docs/screenshot-review.png`;
- the JuaDex name and visual branding, to the extent they are protectable.

If any item was copied or commissioned, record its source, author, applicable
licence/assignment and required notice here before release. If permission cannot
be demonstrated, replace or remove the item. AI assistance does not itself
prove that output is non-infringing; review assisted material for recognizable
third-party expression.

## Repository-history review

At the time of review, reachable history contained one squashed commit and no
previously deleted tracked files. The commit author used a GitHub noreply address.
Pattern-based scans found no credentials or private keys. These checks reduce
risk but do not guarantee that every secret or legal issue is detectable.
