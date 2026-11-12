import hashlib
import time
from pathlib import Path

import httpx


class DownloadError(RuntimeError):
    pass


class PDFDownloader:
    def __init__(
        self,
        *,
        timeout_seconds: float = 60,
        max_bytes: int = 50 * 1024 * 1024,
        max_attempts: int = 3,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_attempts = max_attempts

    def download(self, url: str, destination: Path) -> tuple[str, int]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial_path = destination.with_suffix(destination.suffix + ".part")
        last_error: Exception | None = None

        for attempt in range(self.max_attempts):
            try:
                digest = hashlib.sha256()
                total_bytes = 0
                with httpx.stream(
                    "GET",
                    url,
                    timeout=self.timeout_seconds,
                    follow_redirects=True,
                    headers={"User-Agent": "STF-Jurisprudencias-Coletor/1.0"},
                ) as response:
                    # Before raise_for_status: the CAPTCHA variant of this check answers HTTP 405.
                    if response.headers.get("x-amzn-waf-action"):
                        raise DownloadError(
                            "O STF exigiu uma verificação anti-robô para este arquivo, e o "
                            "programa não contorna essa proteção. Baixe o PDF manualmente "
                            "pelo portal do STF."
                        )
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if "pdf" not in content_type and "octet-stream" not in content_type:
                        raise DownloadError(
                            f"Resposta não identificada como PDF ({content_type or 'sem Content-Type'})"
                        )

                    with partial_path.open("wb") as output:
                        for chunk in response.iter_bytes(chunk_size=64 * 1024):
                            if not chunk:
                                continue
                            total_bytes += len(chunk)
                            if total_bytes > self.max_bytes:
                                raise DownloadError(
                                    f"PDF excedeu o limite de {self.max_bytes} bytes"
                                )
                            digest.update(chunk)
                            output.write(chunk)

                if total_bytes == 0:
                    raise DownloadError(
                        "O STF enviou um arquivo vazio para este documento. "
                        "Tente baixá-lo mais tarde pelo portal do STF."
                    )
                with partial_path.open("rb") as downloaded_file:
                    if downloaded_file.read(5) != b"%PDF-":
                        raise DownloadError("O conteúdo recebido não possui assinatura PDF")
                partial_path.replace(destination)
                return digest.hexdigest(), total_bytes
            except (httpx.HTTPError, OSError, DownloadError) as error:
                last_error = error
                partial_path.unlink(missing_ok=True)
                permanent = isinstance(error, DownloadError) or (
                    isinstance(error, httpx.HTTPStatusError)
                    and error.response.status_code < 500
                    and error.response.status_code not in (408, 429)
                )
                if permanent:
                    break
                if attempt + 1 < self.max_attempts:
                    time.sleep(min(2**attempt, 8))

        raise DownloadError(f"Falha ao baixar PDF: {last_error}") from last_error