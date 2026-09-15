# Contributing to Book-OCR

Thank you for helping improve Book-OCR. Keep changes focused, reviewable, and consistent with the project's local-first design.

## Workflow

1. Fork the repository and create a short-lived branch for one change.
2. Make the smallest coherent implementation and add or update tests.
3. Run the complete offline test suite.
4. Open a focused pull request explaining the problem, the solution, and how it was verified.

```powershell
python -m unittest discover -s tests -v
node tests/test_polling.cjs
git diff --check
```

## Project Safety Rules

- Never commit a real Gemini key, password, token, private certificate, `.bookocr-keys` backup, user database, export, or local configuration.
- Never add private, copyrighted, or personally identifying scanned books or PDFs as test fixtures. Generate minimal synthetic fixtures in temporary directories instead.
- Do not make OCR, retry, quota, or recovery behavior changes without regression tests.
- Preserve loopback-only binding, local data ownership, safe package validation, and separation between application files and user data.
- Tests must mock Gemini. Do not make live API calls in CI or routine test runs.
- Keep dependency additions necessary and document any packaging impact.

## Pull Requests

Describe user-visible behavior, security or migration implications, and the exact commands you ran. Avoid combining unrelated refactors with a feature or bug fix. If a change affects the Windows distribution, also run `.\build_windows.ps1` from PowerShell and report the smoke-test result.
