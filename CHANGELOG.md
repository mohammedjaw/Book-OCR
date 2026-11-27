# Version 0.3.0

- Export available book and collection text as TXT or Markdown during OCR. Exports preserve page order and identify unfinished pages.
- Export and resume incomplete individual books with portable package format v2. Complete books retain format v1. Collection packages still require all volumes to be complete.
- Remove a saved Gemini key with confirmation. The scheduler drops deleted and deselected keys, and selects another enabled key when the active one is removed.
- Encrypted backups now capture the effective SQLite pool. Replace restores the backed-up mode and membership. Merge retains an existing library's selection and imports the backed-up selection into an empty key store.
- OCR waits across workers during HTTP 503 outages, honors cooldowns, and preserves unfinished pages when keys are exhausted. Connection tests distinguish network failures, denied access, invalid credentials, and rate limits.
- Settings displays build provenance and offers an explicit GitHub release check in Arabic, English, and Persian.

The previous Windows release was [v0.2.3, September 15, 2026](https://github.com/mohammedjaw/Book-OCR/releases/tag/v0.2.3), at commit `d6fab8d82ad2241b28f2946bc6cad26098fa57d9`. See the [rollback instructions](ROLLBACK.md).

# Version 0.1.0
- Initial local Arabic digital library
- PDF import and duplicate detection
- SQLite database
- PDF viewer structure
- Gemini API settings
- Arabic RTL interface

# Version 0.2.1
- Added page-level database records
- Added single-page Gemini OCR testing
- Added OCR page status tracking
- Added extracted text display

# Version 0.2.2
- Fixed OCR pages stuck in processing
- Added whole-book OCR workflow
- Added pause/resume
- Added retry failed pages
- Added OCR progress tracking
- Added extracted page browser
- Added page-level text view

# Version 0.2.3
- Added exact and flexible Arabic FTS5 search with collection scopes
- Added multi-volume collections and complete collection package transfer
- Added individual portable book package validation and import/export
- Added password-encrypted Gemini API-key backup and restore
- Added multi-key fallback, per-key quota isolation, and safer OCR recovery
- Added Arabic, English, and Persian UI preferences with light, dark, and system themes
- Added full-text reading, PDF-page navigation, and Word export
- Added a self-contained, no-console Windows x64 `onedir` build
- Moved packaged user data to `%LOCALAPPDATA%\Book-OCR\`
