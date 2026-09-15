## Summary

Explain the focused problem and solution.

## Verification

- [ ] `python -m unittest discover -s tests -v`
- [ ] `node tests/test_polling.cjs`
- [ ] `git diff --check`
- [ ] Windows build and packaged smoke test completed, if packaging or runtime behavior changed

## Safety

- [ ] No real API keys, passwords, tokens, private certificates, user databases, private/copyrighted scanned books, exports, backups, or personal paths are included
- [ ] Gemini calls are mocked in automated tests
- [ ] Local-first storage and loopback-only network behavior are preserved
- [ ] OCR, recovery, quota, or package behavior changes include regression tests

## Notes

Describe migration, dependency, privacy, or packaging effects, or write “None.”
