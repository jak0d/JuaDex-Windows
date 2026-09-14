# Security policy

## Supported versions

Security fixes are provided for the latest release only. Until a compliant
replacement build is published, treat the existing 1.0.0 binary as unsupported.

## Reporting a vulnerability

Please **do not open a public issue** for a suspected vulnerability. Use
GitHub's **Security → Report a vulnerability** private reporting form for this
repository. Include the affected version, impact, reproduction steps and any
suggested remediation. Do not include real or confidential PDFs.

If private vulnerability reporting is not enabled yet, contact the maintainer
through the repository owner's GitHub profile and ask for a private reporting
channel; do not send exploit details in the initial public message.

The maintainer aims to acknowledge reports within 7 days and will coordinate a
fix and disclosure timeline based on severity. Good-faith research that avoids
privacy violations, data destruction and service disruption is welcome.

## Security model and scope

JuaDex processes untrusted PDF and image data locally through native third-party
parsers. A malicious document could therefore exercise vulnerabilities in
PyMuPDF/MuPDF, zxing-cpp, Pillow or Qt even though JuaDex itself makes no network
requests. Keep dependencies patched and obtain releases only from the official
GitHub repository. Verify the published SHA-256 checksums and, when available,
the Windows code signature.

The application does not provide a security boundary for hostile documents and
does not sandbox parser libraries. For high-risk files, process them in an
appropriately isolated Windows environment.

## Maintainer release practices

Official releases must follow `docs/RELEASE_CHECKLIST.md`, including dependency
and vulnerability review, secret scanning, licence validation, a clean test
run, code signing, checksums and archival of corresponding source.
