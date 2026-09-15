# Security Policy

## Supported Version

Security fixes are focused on the latest published Book-OCR release.

## Reporting a Vulnerability

Do not put Gemini API keys, passwords, tokens, private books, user databases, private PDFs, or other sensitive material in a public GitHub issue.

Use GitHub's **Report a vulnerability** option on this repository's Security tab when private vulnerability reporting is available. Include only the minimum reproduction material required and replace any real book content with a synthetic example.

If private vulnerability reporting is unavailable, open a minimal public issue asking a maintainer to arrange a private contact path. Do not include vulnerability details or sensitive attachments in that issue.

If a Gemini API key may have been exposed, revoke or rotate it immediately in the relevant Google account. Removing a key from a file or Git commit does not make the exposed credential safe again.

## Security Scope

Reports concerning loopback isolation, path handling, archive import validation, credential storage or backup, unauthorized data disclosure, dependency packaging, and unsafe OCR-provider error handling are especially useful.

Book-OCR sends rendered page content to the configured Gemini API when OCR is requested. That expected provider communication is not an offline operation; unexpected network or data disclosure beyond that boundary should be reported.
