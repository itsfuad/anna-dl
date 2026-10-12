import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anna_dl.cli import main
from anna_dl.utils import load_json, save_json


class CliTests(unittest.TestCase):
    def run_cli(self, argv):
        with patch.object(sys, 'argv', ['anna-dl'] + argv), patch('anna_dl.download.get_working_mirror', return_value='offline'), patch('anna_dl.download.search_md5_candidates', return_value=[]), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                result = main()
            except SystemExit as error:
                return error.code
            return result or 0

    def test_failed_batches_exit_nonzero_in_sequential_and_parallel_modes(self):
        for parallel in (False, True):
            with self.subTest(parallel=parallel), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                queue, log = root / 'queue.json', root / 'log.json'
                save_json(queue, [{'title': 'Example', 'author': 'Author'}])
                argv = ['download', '--queue-file', str(queue), '--log-file', str(log), '--output-dir', str(root/'downloads')]
                if parallel: argv += ['--parallel']
                self.assertEqual(self.run_cli(argv), 1)
                self.assertEqual(load_json(log)['Example - Author']['status'], 'FAILED')

    def test_parallel_limit_bounds_attempts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            queue, log = root / 'queue.json', root / 'log.json'
            save_json(queue, [{'title': f'Book {i}', 'author': 'Author'} for i in range(3)])
            self.run_cli(['download', '--parallel', '--limit', '1', '--queue-file', str(queue), '--log-file', str(log), '--output-dir', str(root/'downloads')])
            self.assertEqual(list(load_json(log)), ['Book 0 - Author'])

    def test_retry_rechecks_missing_files_marked_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            queue, log = root / 'queue.json', root / 'log.json'
            save_json(queue, [{'title': 'Example', 'author': 'Author'}])
            save_json(log, {'Example - Author': {'status': 'SUCCESS'}})
            self.assertEqual(self.run_cli(['retry', '--queue-file', str(queue), '--log-file', str(log), '--output-dir', str(root/'downloads')]), 1)
            self.assertEqual(load_json(log)['Example - Author']['status'], 'FAILED')

    def test_invalid_worker_count_and_negative_limit_are_usage_errors(self):
        for flags in (['--workers','0'], ['--limit','-1']):
            with self.subTest(flags=flags):
                self.assertEqual(self.run_cli(['download'] + flags), 2)
