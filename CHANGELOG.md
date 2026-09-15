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
