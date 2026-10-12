import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anna_dl.feeder import parse_feeder, run_feeder
from anna_dl.utils import load_json, save_json


class FeederTests(unittest.TestCase):
    def test_stale_ledger_does_not_skip_missing_corrupt_or_relocated_books(self):
        for previous in ('missing', 'corrupt', 'other-folder'):
            with self.subTest(previous=previous), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                feeder = root / 'feeder.txt'
                feeder.write_text('Example | Author\n', encoding='utf-8')
                book = parse_feeder(feeder)[0][0]
                output = root / 'downloads'
                output.mkdir()
                target = output / 'Example - Author.pdf'
                old_path = target
                if previous == 'corrupt':
                    target.write_bytes(b'garbage' * 2000)
                elif previous == 'other-folder':
                    old_path = root / 'old.pdf'
                    old_path.write_bytes(b'%PDF-1.7\n' + b'x' * 12000)
                ledger = root / 'ledger.json'
                save_json(ledger, {book['key']: {'status': 'downloaded', 'path': str(old_path)}})

                def download(book, mirror, directory):
                    target.write_bytes(b'%PDF-1.7\n' + b'x' * 12000)
                    return target

                with patch('anna_dl.feeder.get_working_mirror', return_value='offline'), patch('anna_dl.feeder.download_book', side_effect=download), contextlib.redirect_stdout(io.StringIO()):
                    stats = run_feeder(feeder, output, ledger)
                self.assertEqual(stats['downloaded'], 1)
                self.assertEqual(stats['already_had'], 0)
                self.assertEqual(load_json(ledger)[book['key']]['path'], str(target))

    def test_valid_existing_book_is_skipped_without_a_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            feeder = root / 'feeder.txt'
            feeder.write_text('Example | Author\n', encoding='utf-8')
            (root / 'Example - Author.pdf').write_bytes(b'%PDF-1.7\n' + b'x' * 12000)
            with contextlib.redirect_stdout(io.StringIO()):
                stats = run_feeder(feeder, root, root / 'ledger.json')
            self.assertEqual(stats['already_had'], 1)
            self.assertEqual(stats['downloaded'], 0)
