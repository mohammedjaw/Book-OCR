"""Keep one scheduler process per local library, including during startup recovery."""
from contextlib import contextmanager
import os

@contextmanager
def library_lock(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell() == 0: handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('This Book-OCR library is already open. Run one server process per library.') from None
        try: yield
        finally:
            handle.seek(0)
            if os.name == 'nt': msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
