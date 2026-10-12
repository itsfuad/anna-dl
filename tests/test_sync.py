import tempfile
import unittest
from pathlib import Path

from anna_dl.sync import sync_log_from_disk
from anna_dl.utils import load_json, save_json


class SyncTests(unittest.TestCase):
    def test_sync_rejects_prefix_matches_invalid_files_and_wrong_categories(self):
        for case in ('prefix', 'empty', 'html', 'wrong-category'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                output = root / 'downloads'
                output.mkdir()
                name = 'Example - Author Other.pdf' if case == 'prefix' else 'Example - Author.pdf'
                payload = b'' if case == 'empty' else b'\n<HTML>' + b'x' * 12000 if case == 'html' else b'%PDF-1.7\n' + b'x' * 12000
                (output / name).write_bytes(payload)
                book = {'title': 'Example', 'author': 'Author'}
                if case == 'wrong-category':
                    book['category'] = 'Science'
                queue, log = root / 'queue.json', root / 'log.json'
                save_json(queue, [book])
                save_json(log, {'Example - Author': {'status': 'SUCCESS'}})
                stats = sync_log_from_disk(output, queue, log)
                self.assertEqual(stats['success'], 0)
                self.assertEqual(stats['failed'], 1)
                self.assertEqual(load_json(log)['Example - Author']['status'], 'FAILED')

    def test_sync_finds_exact_valid_file_in_category(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / 'downloads' / 'Science'
            output.mkdir(parents=True)
            target = output / 'Example - Author.pdf'
            target.write_bytes(b'%PDF-1.7\n' + b'x' * 12000)
            queue, log = root / 'queue.json', root / 'log.json'
            save_json(queue, [{'title': 'Example', 'author': 'Author', 'category':'Science'}])
            stats = sync_log_from_disk(root / 'downloads', queue, log)
            self.assertEqual(stats['success'], 1)
            self.assertEqual(load_json(log)['Example - Author']['path'], str(target))
