from pydantic import BaseModel
from enum import Enum
from pathlib import Path

from langchain_docling.loader import DoclingLoader
from langchain_docling.loader import ExportType

# class DocumentType(str, Enum):
#     PRESCRIPTION = "PRESCRIPTION"
#     HOSPITAL_BILL = "HOSPITAL_BILL"
#     PHARMACY_BILL = "PHARMACY_BILL"
#     LAB_REPORT = "LAB_REPORT"
#     DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
#     DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
#     DENTAL_REPORT = "DENTAL_REPORT"
#     UNKNOWN = "UNKNOWN"

# class DocumentClassification(BaseModel):
#     document_type: DocumentType
#     confidence: float
#     reasoning: str
    
# class ExtractedDocument(BaseModel):
#     document_type: str
#     patient_name: str | None
#     doctor_name: str | None
#     doctor_registration: str | None
#     diagnosis: str | None
#     hospital_name: str | None
#     date: str | None
#     total_amount: float | None
#     line_items: list[dict] = []
#     tests_ordered: list[str] = []
#     confidence: float

def docling_document_to_text(path: str):

    path = Path(path).resolve()

    loader = DoclingLoader(
        file_path=str(path),
        export_type=ExportType.MARKDOWN
    )

    docs = loader.load()

    markdown_text = "\n\n".join(
        doc.page_content
        for doc in docs
    )

    return markdown_text
