# Contributing

Thank you for helping improve JuaDex.

## Before submitting

1. Open an issue for substantial changes so licensing and design can be agreed.
2. Do not submit confidential PDFs, credentials, personal data, proprietary
   code, or assets copied from another project without compatible permission.
3. Identify all third-party material and preserve its copyright, licence and
   notice requirements in `THIRD_PARTY_NOTICES.md` and `LICENSES/`.
4. Run `QT_QPA_PLATFORM=offscreen pytest` and keep the offline guarantees intact.

## Developer Certificate of Origin

Contributions use the [Developer Certificate of Origin 1.1](https://developercertificate.org/).
Add a sign-off to every commit:

```text
Signed-off-by: Your Name <your-email@example.com>
```

Use `git commit -s` to add it. By signing off, you certify that you wrote the
contribution or otherwise have the right to submit it under the project's MIT
licence, and that the contribution may be public. This is a provenance record,
not a transfer of your copyright.

## Licensing

New original contributions are accepted under the MIT licence in `LICENSE`.
Third-party components keep their own licences. Because official binaries use
AGPL- and LGPL-covered dependencies, changing dependencies or packaging needs a
fresh compliance review; see `docs/RELEASE_CHECKLIST.md`.

AI-assisted contributions are not automatically rejected, but the contributor
remains responsible for reviewing them, verifying that no incompatible or
unattributed material was reproduced, and accurately disclosing meaningful
third-party sources.
