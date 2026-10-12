import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from anna_dl.download import download_file


class DownloadTests(unittest.TestCase):
    def test_new_candidate_does_not_resume_an_unrelated_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / 'book.pdf'
            partial = dest.with_suffix('.pdf.tmp')
            partial.write_bytes(b'%PDF-old\n' + b'A' * 12000)
            content = b'%PDF-new\n' + b'B' * 15000

            def transfer(cmd, **kwargs):
                # Model curl -C -: append bytes starting at the existing offset.
                offset = partial.stat().st_size if partial.exists() else 0
                with partial.open('ab') as stream:
                    stream.write(content[offset:])
                return SimpleNamespace(returncode=0)

            with patch('anna_dl.download.subprocess.run', side_effect=transfer):
                self.assertTrue(download_file('https://example.invalid/new', '', dest))
            self.assertEqual(dest.read_bytes(), content)
