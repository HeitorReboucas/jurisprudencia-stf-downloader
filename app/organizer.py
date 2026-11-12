import re
from pathlib import Path

from app.stf import STFDocument


FOLDER_NAMES = {
    "acordaos": "Acórdãos",
    "decisoes_monocraticas": "Decisões Monocráticas",
}


def pdf_path(root: Path, document: STFDocument) -> Path:
    year = document.document_date[:4] if document.document_date else "sem_data"
    folder_name = FOLDER_NAMES[document.content_type]
    safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", document.title).strip(" .")
    safe_title = safe_title[:140] or "documento"
    safe_key = re.sub(r"[^A-Za-z0-9_-]", "_", document.document_key)[-40:]
    return root / "STF" / folder_name / year / f"{safe_title}_{safe_key}.pdf"