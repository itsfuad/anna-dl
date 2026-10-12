import locale
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from anna_dl.config import ANNA_MIRRORS, HEADERS
from anna_dl.download import download_book
from anna_dl.search import get_working_mirror
from anna_dl.utils import load_json, save_json, existing_download

FEEDER_KEYS = ('title', 'author', 'format', 'isbn', 'query', 'folder')
FORMATS = ('pdf', 'epub')

DOWNLOADED = 'downloaded'
NOT_AVAILABLE = 'not_available'

FEEDER_TEMPLATE = """\
# =============================================================================
#  anna-dl FEEDER LIST
#
#  One book per line. Run it from the GUI (Feeder tab -> Run feeder), or with:
#      python -m anna_dl feed
#
#  HOW IT WORKS
#    1. The books below are searched and downloaded from top to bottom.
#    2. A book that can't be found is skipped (so it doesn't hold up the list)
#       and recorded in feeder_ledger.json as "not_available".
#    3. When the list is finished, every "not_available" book gets one more
#       try at the very end, including books that failed on earlier runs.
#    4. Books the ledger marks "downloaded" are skipped on later runs, so you
#       can keep adding lines here and just run the feeder again.
#       To download a book again, delete its entry from feeder_ledger.json.
#
#  LINE FORMAT
#    Title | Author | parameter=value | parameter=value ...
#
#    - Separate fields with "|". Spaces around them don't matter.
#    - The first unlabeled field is the title, the second is the author.
#      A bare "pdf" or "epub" sets the format.
#    - Lines starting with "#" are comments. Blank lines are ignored.
#
#  PARAMETERS
#    title=   Book title. Required, unless isbn= is given.
#    author=  Author name. Optional, but gives much more accurate matches.
#    format=  pdf or epub: the format you prefer. If it isn't available,
#             another format is downloaded instead.
#             Default: the format picked in the GUI (or --format, default pdf).
#    isbn=    ISBN-10 or ISBN-13, dashes allowed. Searched first, to get one
#             exact edition. Works without a title (the file is then named
#             after the ISBN), but add the title too when you can: every
#             result is checked against the title/author before downloading,
#             and an ISBN alone can't catch a mislabelled file.
#    query=   Your own search text, tried before the automatic searches.
#             Handy for a specific translation or edition, or odd spellings.
#    folder=  Save into a subfolder of the download folder, up to two levels:
#             folder=Philosophy   or   folder=Philosophy/Stoics
#
#  EXAMPLES  (delete the "#" at the start of a line to use it)
#    Pride and Prejudice | Jane Austen
#    Moby-Dick | Herman Melville | epub
#    The Origin of Species | Charles Darwin | format=pdf | folder=Science
#    title=Meditations | author=Marcus Aurelius | query=meditations george long | folder=Philosophy/Stoics
#    Frankenstein | Mary Shelley | isbn=9780141439471 | epub
#    isbn=978-0-14-143951-8
#
# =============================================================================
#  YOUR BOOKS (one per line, below this line)

"""


def ensure_feeder_file(path: Path) -> bool:
    """Creates the feeder file from the template if it doesn't exist. Returns True if it was created."""
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FEEDER_TEMPLATE, encoding='utf-8')
    return True


def parse_feeder_line(line: str) -> Dict[str, str]:
    """
    Parses one 'Title | Author | key=value ...' line into a book dict.
    Raises ValueError with a human-readable message if the line is invalid.
    """
    fields: Dict[str, str] = {}
    positional: List[str] = []
    for part in line.split('|'):
        part = part.strip()
        if not part:
            continue
        key, sep, value = part.partition('=')
        key = key.strip().lower()
        # Only known keys count as labels, so titles like "E=mc2" stay intact
        if sep and key in FEEDER_KEYS:
            if key in fields:
                raise ValueError(f"'{key}=' is given more than once")
            fields[key] = value.strip()
        else:
            positional.append(part)

    for value in positional:
        if value.lower() in FORMATS:
            if 'format' in fields:
                raise ValueError("format is given more than once")
            fields['format'] = value
        elif 'title' not in fields:
            fields['title'] = value
        elif 'author' not in fields:
            fields['author'] = value
        else:
            raise ValueError(f"don't know what '{value}' is; label it, e.g. query={value}")

    title = fields.get('title', '')
    fmt = fields.get('format', '').lower()
    if fmt and fmt not in FORMATS:
        raise ValueError(f"format must be pdf or epub, not '{fields['format']}'")

    isbn = re.sub(r'[\s-]', '', fields.get('isbn', '')).upper()
    if isbn and not re.fullmatch(r'\d{13}|\d{9}[\dX]', isbn):
        raise ValueError(f"'{fields['isbn']}' is not a valid ISBN-10 or ISBN-13")
    if not title and not isbn:
        raise ValueError("needs a title (or isbn=...)")

    folders = [p.strip() for p in re.split(r'[\\/]', fields.get('folder', '')) if p.strip()]
    if len(folders) > 2 or any(p in ('.', '..') for p in folders):
        raise ValueError("folder must be one or two plain names, e.g. folder=Philosophy/Stoics")

    return {
        'title': title or isbn,
        'author': fields.get('author', ''),
        'isbn': isbn,
        'search_query': fields.get('query', ''),
        'prefer_format': fmt,
        'category_group': folders[0] if folders else '',
        'subcategory': folders[1] if len(folders) > 1 else '',
    }


def _read_lines(path: Path) -> List[str]:
    try:
        return path.read_text(encoding='utf-8-sig').splitlines()
    except UnicodeDecodeError:
        # Saved as ANSI by an older editor
        return path.read_text(encoding=locale.getpreferredencoding(False), errors='replace').splitlines()


def _ledger_key(book: Dict[str, Any]) -> str:
    return ' | '.join((book['title'], book['author'], book['isbn'])).lower()


def parse_feeder(feeder_file: Path) -> Tuple[List[Dict[str, Any]], List[Tuple[int, str]]]:
    """
    Reads the feeder file. Returns (books, problems) where problems is a list of
    (line_number, message) for lines that were skipped.
    """
    books: List[Dict[str, Any]] = []
    problems: List[Tuple[int, str]] = []
    seen: Dict[str, int] = {}

    for lineno, raw in enumerate(_read_lines(Path(feeder_file)), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        try:
            book = parse_feeder_line(line)
        except ValueError as e:
            problems.append((lineno, str(e)))
            continue

        key = _ledger_key(book)
        if key in seen:
            problems.append((lineno, f"duplicate of line {seen[key]}"))
            continue
        seen[key] = lineno
        book['key'] = key
        book['line'] = lineno
        books.append(book)

    return books, problems


def _record(ledger: Dict[str, Any], book: Dict[str, Any], path: Optional[Path], attempted: bool = True) -> None:
    entry = ledger.setdefault(book['key'], {})
    entry.update({
        'title': book['title'],
        'author': book['author'],
        'isbn': book['isbn'],
        'status': DOWNLOADED if path else NOT_AVAILABLE,
    })
    if path:
        entry['path'] = str(path)
    else:
        entry.pop('path', None)
    if attempted:
        entry['attempts'] = entry.get('attempts', 0) + 1
        entry['last_attempt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _stop_requested(stop_event: Optional[threading.Event]) -> bool:
    return stop_event is not None and stop_event.is_set()


def run_feeder(
    feeder_file: Path,
    output_dir: Path,
    ledger_file: Path,
    default_format: str = 'pdf',
    stop_event: Optional[threading.Event] = None
) -> Dict[str, Any]:
    """
    Downloads every book listed in the feeder file.
    Books that can't be found are skipped, recorded in the ledger as not available,
    and retried at the very end, together with those that failed on earlier runs.
    """
    output_dir = Path(output_dir)
    books, problems = parse_feeder(feeder_file)
    for lineno, problem in problems:
        print(f"[!] {Path(feeder_file).name} line {lineno}: {problem} (skipped)")

    stats: Dict[str, Any] = {
        'listed': len(books), 'downloaded': 0, 'already_had': 0,
        'not_available': 0, 'pending': 0, 'invalid_lines': len(problems), 'stopped': False
    }
    if not books:
        print(f"[!] No books listed in {feeder_file} yet. Add one per line, e.g.:  Pride and Prejudice | Jane Austen")
        return stats

    ledger = load_json(ledger_file, default={})
    first_pass: List[Dict[str, Any]] = []
    last_pass: List[Dict[str, Any]] = []
    for book in books:
        status = ledger.get(book['key'], {}).get('status')
        existing = existing_download(book, output_dir)
        if existing:
            _record(ledger, book, existing, attempted=False)
            stats['already_had'] += 1
            continue
        # Books that weren't available on an earlier run wait until the very end
        (last_pass if status == NOT_AVAILABLE else first_pass).append(book)
    save_json(ledger_file, ledger)

    print(f"[*] {len(books)} book(s) listed: {stats['already_had']} already downloaded, "
          f"{len(first_pass)} to fetch, {len(last_pass)} not available last time (retried at the end)")

    if first_pass or last_pass:
        output_dir.mkdir(parents=True, exist_ok=True)
        mirror = get_working_mirror(ANNA_MIRRORS, HEADERS)

        def attempt(book: Dict[str, Any]) -> bool:
            path = download_book(dict(book, prefer_format=book['prefer_format'] or default_format), mirror, output_dir)
            _record(ledger, book, path)
            save_json(ledger_file, ledger)
            if path:
                stats['downloaded'] += 1
            return path is not None

        for i, book in enumerate(first_pass, 1):
            if _stop_requested(stop_event):
                break
            print(f"\n[{i}/{len(first_pass)}] line {book['line']}", end='')
            if not attempt(book):
                print("    [-] Not available right now: recorded in the ledger, will retry at the very end.", flush=True)
                last_pass.append(book)

        if last_pass and not _stop_requested(stop_event):
            print(f"\n===== Final pass: retrying {len(last_pass)} book(s) that weren't available =====")
            for i, book in enumerate(last_pass, 1):
                if _stop_requested(stop_event):
                    break
                print(f"\n[retry {i}/{len(last_pass)}] line {book['line']}", end='')
                attempt(book)

    stats['stopped'] = _stop_requested(stop_event)
    not_available = [b for b in books if ledger.get(b['key'], {}).get('status') == NOT_AVAILABLE]
    stats['not_available'] = len(not_available)
    stats['pending'] = sum(1 for b in books if b['key'] not in ledger)

    print("\n===== Feeder summary =====")
    if stats['stopped']:
        print("  Stopped early. Progress is saved; run the feeder again to continue.")
    print(f"  Downloaded this run : {stats['downloaded']}")
    print(f"  Already downloaded  : {stats['already_had']}")
    print(f"  Not available       : {stats['not_available']}")
    for b in not_available:
        print(f"    - line {b['line']}: {b['title']}" + (f" ({b['author']})" if b['author'] else ''))
    if stats['pending']:
        print(f"  Not attempted yet   : {stats['pending']}")
    if problems:
        print(f"  Invalid lines       : {len(problems)} (see warnings at the top)")
    print(f"  Ledger              : {ledger_file}", flush=True)
    return stats
