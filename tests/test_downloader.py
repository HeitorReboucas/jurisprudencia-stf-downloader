import hashlib
from unittest.mock import MagicMock, patch

import pytest

from app.downloader import DownloadError, PDFDownloader


def test_downloader_validates_pdf_and_returns_sha256(tmp_path) -> None:
    content = b"%PDF-1.7\nunit test\n%%EOF"
    response = MagicMock()
    response.headers = {"content-type": "application/pdf"}
    response.iter_bytes.return_value = [content]

    with patch("app.downloader.httpx.stream") as stream:
        stream.return_value.__enter__.return_value = response
        destination = tmp_path / "document.pdf"
        digest, size = PDFDownloader(max_attempts=1).download(
            "https://portal.stf.jus.br/documento.pdf", destination
        )

    assert destination.read_bytes() == content
    assert digest == hashlib.sha256(content).hexdigest()
    assert size == len(content)


def test_downloader_rejects_non_pdf_response(tmp_path) -> None:
    response = MagicMock()
    response.headers = {"content-type": "text/html"}

    with patch("app.downloader.httpx.stream") as stream:
        stream.return_value.__enter__.return_value = response
        with pytest.raises(DownloadError, match="não identificada como PDF"):
            PDFDownloader(max_attempts=3).download(
                "https://portal.stf.jus.br/documento", tmp_path / "document.pdf"
            )

    assert stream.call_count == 1

    assert not (tmp_path / "document.pdf").exists()

def test_downloader_retries_rate_limited_response(tmp_path) -> None:
    import httpx

    limited = MagicMock()
    limited.raise_for_status.side_effect = httpx.HTTPStatusError(
        "429", request=MagicMock(), response=MagicMock(status_code=429)
    )
    ok = MagicMock()
    ok.headers = {"content-type": "application/pdf"}
    ok.iter_bytes.return_value = [b"%PDF-1.7\n%%EOF"]
    contexts = [MagicMock(), MagicMock()]
    contexts[0].__enter__.return_value = limited
    contexts[1].__enter__.return_value = ok

    with patch("app.downloader.httpx.stream", side_effect=contexts) as stream, patch(
        "app.downloader.time.sleep"
    ):
        PDFDownloader(max_attempts=3).download(
            "https://portal.stf.jus.br/documento.pdf", tmp_path / "document.pdf"
        )

    assert stream.call_count == 2
