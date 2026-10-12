import json
import math
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

def sanitize_filename(name: str) -> str:
    """
    Strips illegal filesystem characters and limits filename length to 150 characters.
    """
    name = re.sub(r'[\\/*?:"<>|]', '', name)
    return name.strip()[:150]

def clean_query_text(text: str) -> str:
    """
    Removes parentheticals, bracketed notations, and common edition markers.
    """
    text = re.sub(r'\(.*?\)', '', text)
    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\b(ed\.|eds\.|vol\.|rev\.|2nd|3rd|4th|5th)\b', '', text, flags=re.IGNORECASE)
    return text.strip()

def build_queries(title: str, author: str = '', search_query: str = '') -> List[str]:
    """
    Generates an ordered progression of fallback queries:
    1. Explicit custom search query (if supplied)
    2. Full cleaned title + primary author
    3. Short title (pre-colon/dash) + author last name
    4. Short title alone
    5. Cleaned full title alone (if different from short title)
    6. Author last name + top keywords
    7. Niche keywords alone
    """
    queries = []
    if search_query:
        queries.append(search_query)

    clean_title = clean_query_text(title)
    clean_author = clean_query_text(author)
    primary_author = clean_author.split(',')[0].strip() if clean_author else ''
    last_name = primary_author.split()[-1] if primary_author else ''

    if primary_author:
        queries.append(f"{clean_title} {primary_author}".strip())
    else:
        queries.append(clean_title)

    short_title = re.split(r'[:\-—]', clean_title)[0].strip()
    if last_name:
        queries.append(f"{short_title} {last_name}".strip())
    if short_title:
        queries.append(short_title)
    if clean_title and clean_title != short_title:
        queries.append(clean_title)

    stopwords = {'with', 'from', 'this', 'that', 'then', 'than', 'into', 'upon', 'over', 'some', 'such', 'about', 'guide', 'the', 'a', 'an', 'and', 'of', 'in', 'on', 'for', 'to', 'how'}
    sig_words = [w for w in re.findall(r'\b[a-zA-Z]{3,}\b', clean_title) if w.lower() not in stopwords]
    if sig_words:
        if last_name:
            queries.append(f"{last_name} {' '.join(sig_words[:2])}".strip())
            queries.append(f"{last_name} {' '.join(sig_words[:3])}".strip())
        queries.append(f"{' '.join(sig_words[:2])}".strip())

    words = [w for w in re.findall(r'\b\w{4,}\b', clean_title.lower()) if w not in stopwords]
    niche_keywords = " ".join(words[:4])
    if niche_keywords and last_name:
        queries.append(f"{niche_keywords} {last_name}".strip())

    deduped = []
    for q in queries:
        q = q.strip()
        if q and q not in deduped:
            deduped.append(q)

    return deduped

_MATCH_STOPWORDS = {'the', 'a', 'an', 'and', 'of', 'in', 'on', 'for', 'to', 'with', 'from', 'by', 'or', 'at'}

def _match_tokens(text: str) -> List[str]:
    """Lowercased, accent-free words with a trailing plural 's' removed, for loose comparisons."""
    text = unicodedata.normalize('NFKD', text.lower())
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    words = [w for w in re.findall(r'[^\W_]+', text) if w not in _MATCH_STOPWORDS]
    return [w[:-1] if len(w) > 3 and w.endswith('s') else w for w in words]

def _isbn13(isbn: str) -> str:
    """Normalizes an ISBN-10 or ISBN-13 to its ISBN-13 digits."""
    isbn = re.sub(r'[^0-9X]', '', isbn.upper())
    if len(isbn) == 10:
        core = '978' + isbn[:9]
        check = (10 - sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(core)) % 10) % 10
        return core + str(check)
    return isbn

def candidate_matches(title: str, author: str, isbn: str, meta: Dict[str, str]) -> bool:
    """
    Decides whether a search result's metadata (title/author/isbn from its details page)
    plausibly is the requested book, so loose search hits for an unknown title aren't
    downloaded under its name. Untitled records can't be verified and are rejected.
    """
    if isbn and title == isbn:
        # ISBN-only request: the ISBN is all there is to compare
        listed = {_isbn13(i) for i in re.split(r'[;,\s]+', meta.get('isbn', '')) if i}
        return _isbn13(isbn) in listed

    if not meta.get('title'):
        return False

    short_title = re.split(r'[:;]| - | — ', clean_query_text(title))[0]
    wanted = [w for w in _match_tokens(short_title) if len(w) >= 3 or w.isdigit()] or _match_tokens(short_title)
    if wanted:
        have = set(_match_tokens(meta['title']))
        hits = sum(1 for w in wanted if w in have)
        if hits < math.ceil(len(wanted) * 0.75):
            return False

    if author and meta.get('author'):
        wanted_names = [w for w in _match_tokens(clean_query_text(author)) if len(w) >= 3]
        if wanted_names and not set(wanted_names) & set(_match_tokens(meta['author'])):
            return False

    return True

def load_json(filepath: Path, default: Any = None) -> Any:
    """
    Safely reads JSON files, returning default fallback on missing or corrupt files.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(filepath: Path, data: Any) -> None:
    """
    Performs atomic writes using tempfile + os.replace to prevent file corruption.
    """
    filepath = Path(filepath)
    dir_name = filepath.parent
    dir_name.mkdir(parents=True, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(dir=dir_name, text=True)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, filepath)
