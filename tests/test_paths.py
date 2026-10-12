import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anna_dl.download import download_book
from anna_dl.utils import existing_download, sanitize_filename


class PathTests(unittest.TestCase):
    def test_long_and_unicode_book_names_preserve_extension_and_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            paths = []

            def transfer(url, referer, path):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'%PDF-1.7\n' + b'x' * 12000)
                return True

            with patch('anna_dl.download.search_md5_candidates', return_value=['a' * 32]), patch('anna_dl.download.get_direct_download_url', return_value=('https://example.invalid/book','pdf','')), patch('anna_dl.download.download_file', side_effect=transfer), contextlib.redirect_stdout(io.StringIO()):
                for title in ('A' * 160 + ' First', 'A' * 160 + ' Second', 'বাংলা' * 40):
                    book = {'title': title, 'author': 'Author', 'category': 'Science'}
                    path = download_book(book, 'offline', output)
                    self.assertIsNotNone(path)
                    self.assertEqual(path.suffix, '.pdf')
                    self.assertLessEqual(len(path.name.encode('utf-8')), 150)
                    self.assertEqual(existing_download(book, output), path)
                    paths.append(path)
            self.assertEqual(len(set(paths)), 3)

    def test_windows_reserved_names_trailing_dots_and_controls_are_safe(self):
        for value, expected in [('CON','_CON'), ('nul.txt','_nul.txt'), ('LPT1','_LPT1'), ('..','_'), ('Name. ','Name'), ('A\x00B\nC','ABC')]:
            with self.subTest(value=value):
                self.assertEqual(sanitize_filename(value), expected)
