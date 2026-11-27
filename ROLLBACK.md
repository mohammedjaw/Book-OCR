# Windows rollback

The previous stable release is [Book-OCR v0.2.3](https://github.com/mohammedjaw/Book-OCR/releases/tag/v0.2.3), published September 15, 2026 at commit `d6fab8d82ad2241b28f2946bc6cad26098fa57d9`. Its Windows ZIP has SHA-256 `41114cb5502240480a6fa0970595dce5e23c9cfb20c4da2c17c786e89dde23a1`.

1. Before upgrading, pause OCR, close Book-OCR and stop its server. Back up the entire library root, including books, database, and configuration. The Windows default is `%LOCALAPPDATA%\Book-OCR`. If you set `BOOK_OCR_DATA_DIR`, back up that directory instead. Keep the backup private.
2. To return to v0.2.3, stop the v0.3.0 server and keep a separate backup of the current library. Download the earlier ZIP, verify it with `Get-FileHash -Algorithm SHA256`, and extract it into a separate application directory.
3. For an exact rollback, retain the newer library in a separate location and restore the pre-upgrade backup to its **original absolute path** before launching the earlier executable. The database records absolute PDF paths. Restoring the pre-upgrade snapshot restores its earlier books, text and key settings.
4. Launch the earlier executable with its complete `_internal` folder. To check the old program independently, point `BOOK_OCR_DATA_DIR` at a fresh empty directory and use a free port.

v0.2.3 cannot import incomplete v2 book packages. Keep v0.3.0 available to resume those books or export their available text. Complete individual v1 packages remain compatible.
