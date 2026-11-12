from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode


CONTENT_BASES = {
    "acordaos": "acordaos",
    "decisoes_monocraticas": "decisoes",
    "sumulas": "sumulas",
    "informativos": "informativos",
}
# The "base" the portal writes in each result; searching base=informativos returns "novo_informativo".
RESULT_BASES = {
    "acordaos": {"acordaos"},
    "decisoes_monocraticas": {"decisoes"},
    "sumulas": {"sumulas"},
    "informativos": {"informativos", "novo_informativo"},
}


class STFTemporaryUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class STFDocument:
    document_key: str
    title: str
    process: str | None
    process_class: str | None
    content_type: str
    document_date: str | None
    source_url: str
    pdf_url: str | None


def normalize_document(source: dict[str, Any], content_type: str) -> STFDocument:
    document_id = source.get("id") or source.get("dg_unique") or source.get("titulo")
    if not document_id:
        raise ValueError("Documento do STF sem identificador estável")

    document_number = source.get("processo_codigo_completo") or source.get("titulo")
    pdf_url = source.get("inteiro_teor_url")
    # The portal sends some links (e.g. monocratic decisions) as http; the same file is served over https.
    if pdf_url and pdf_url.startswith("http://"):
        pdf_url = "https://" + pdf_url.removeprefix("http://")
    return STFDocument(
        document_key=f"{source.get('base', content_type)}:{document_id}",
        title=str(source.get("titulo") or document_number or document_id),
        process=document_number,
        process_class=source.get("processo_classe_processual_unificada_sigla"),
        content_type=content_type,
        document_date=source.get("publicacao_data") or source.get("julgamento_data"),
        source_url=(
            "https://jurisprudencia.stf.jus.br/pages/search?"
            + urlencode(
                {
                    "base": CONTENT_BASES[content_type],
                    "queryString": str(document_id),
                }
            )
        ),
        pdf_url=pdf_url,
    )
