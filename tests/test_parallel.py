import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anna_dl.download import download_parallel
from anna_dl.utils import load_json


class ParallelTests(unittest.TestCase):
    def test_parallel_uses_isbn_and_format_preference(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            book = {'title': 'Example', 'author': 'Author', 'isbn':'9780141439518', 'prefer_format':'epub'}

            def search(query, mirror, max_candidates=15, prefer_format='pdf'):
                return ['a' * 32] if query == '9780141439518' and prefer_format == 'epub' else []

            def transfer(url, referer, dest):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b'%PDF-1.7\n' + b'x' * 12000)
                return True

            with patch('anna_dl.download.get_working_mirror', return_value='offline'), patch('anna_dl.download.search_md5_candidates', side_effect=search), patch('anna_dl.download.get_direct_download_url', return_value=('https://example.invalid/book', 'pdf', '')), patch('anna_dl.download.download_file', side_effect=transfer), contextlib.redirect_stdout(io.StringIO()):
                download_parallel([book], root / 'downloads', root / 'log.json', max_workers=1)
            log = load_json(root / 'log.json')
            self.assertEqual(log['Example - Author']['status'], 'SUCCESS')
            self.assertTrue(Path(log['Example - Author']['path']).is_file())

    def test_parallel_rechecks_stale_success_and_keeps_all_worker_results(self):
        from anna_dl.utils import save_json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            books = [{'title': f'Book {i}', 'author': 'Author'} for i in range(4)]
            log_file = root / 'log.json'
            save_json(log_file, {'Book 0 - Author': {'status': 'SUCCESS', 'path': str(root/'missing.pdf')}})
            with patch('anna_dl.download.get_working_mirror', return_value='offline'), patch('anna_dl.download.search_md5_candidates', return_value=[]), contextlib.redirect_stdout(io.StringIO()):
                download_parallel(books, root / 'downloads', log_file, max_workers=2)
            self.assertEqual(len(load_json(log_file)), 4)
            self.assertTrue(all(entry['status'] == 'FAILED' for entry in load_json(log_file).values()))
