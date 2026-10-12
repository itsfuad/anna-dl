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

    def test_error_pages_and_unrelated_files_are_rejected_by_both_transports(self):
        from requests import Response
        invalid = [b'\n<HTML>Error' + b'x' * 12000, b'garbage' + b'x' * 12000]
        for payload in invalid:
            for transport in ('curl', 'requests'):
                with self.subTest(transport=transport, prefix=payload[:15]), tempfile.TemporaryDirectory() as folder:
                    dest = Path(folder) / 'book.pdf'

                    def transfer(cmd, **kwargs):
                        Path(cmd[-1]).write_bytes(payload)
                        return SimpleNamespace(returncode=0)

                    response = Response()
                    response.status_code = 200
                    response._content = payload
                    response._content_consumed = True
                    curl = transfer if transport == 'curl' else FileNotFoundError('curl')
                    with patch('anna_dl.download.subprocess.run', side_effect=curl), patch('anna_dl.download.requests.get', return_value=response):
                        self.assertFalse(download_file('https://example.invalid/error', '', dest))
                    self.assertFalse(dest.exists())

    def test_valid_pdf_and_epub_are_saved_but_generic_zip_is_rejected(self):
        import io
        import zipfile
        pdf = b'%PDF-1.7\n' + b'A' * 12000 + b'\n%%EOF\n'
        packages = []
        for epub in (True, False):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr('payload', b'A' * 12000)
                if epub:
                    archive.writestr('mimetype', 'application/epub+zip')
            packages.append(stream.getvalue())
        for payload, valid in ((pdf, True), (packages[0], True), (packages[1], False)):
            with self.subTest(valid=valid, prefix=payload[:4]), tempfile.TemporaryDirectory() as folder:
                dest = Path(folder) / 'book.pdf'

                def transfer(cmd, **kwargs):
                    Path(cmd[-1]).write_bytes(payload)
                    return SimpleNamespace(returncode=0)

                with patch('anna_dl.download.subprocess.run', side_effect=transfer), patch('anna_dl.download.requests.get', side_effect=ConnectionError('offline')):
                    self.assertEqual(download_file('https://example.invalid/book', '', dest), valid)
                if valid:
                    self.assertEqual(dest.read_bytes(), payload)
                else:
                    self.assertFalse(dest.exists())
