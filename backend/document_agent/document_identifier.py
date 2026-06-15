from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field

from langchain_docling.loader import DoclingLoader
from langchain_docling.loader import ExportType
import sub_agent.llm
import re

import json

class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    PHARMACY_BILL = "PHARMACY_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"
    UNKNOWN = "UNKNOWN"


class LineItem(BaseModel):
    quantity: int | None = None
    description: str | None = None
    maker: str | None = None
    batch_number: str | None = None
    expiry_date: str | None = None
    amount: float | None = None


class DocumentClassification(BaseModel):
    document_type: DocumentType
    confidence: float
    reasoning: str

class ExtractedDocument(BaseModel):
    document_type: DocumentType = DocumentType.UNKNOWN

    patient_name: str | None = None

    doctor_name: str | None = None
    doctor_registration: str | None = None

    diagnosis: str | None = None

    hospital_name: str | None = None

    date: str | None = None

    total_amount: float | None = None

    medicines: list[str] = Field(default_factory=list)

    line_items: list[LineItem] = Field(default_factory=list)

    tests_ordered: list[str] = Field(default_factory=list)

    confidence: float = 0.0
    
    


class DocumentAgent:

    def __init__(self):
        self.llm_client = sub_agent.llm.LLMClient()

    def parse_llm_response(self,response: str):

        match = re.search(
            r"```json\s*(.*?)\s*```",
            response,
            re.DOTALL
        )

        if match:
            response = match.group(1)

        data = json.loads(response)
        return data

    def _document_to_text(self, path: str):

        loader = DoclingLoader(
            file_path=str(Path(path).resolve()),
            export_type=ExportType.MARKDOWN
        )

        docs = loader.load()

        return "\n\n".join(
            doc.page_content
            for doc in docs
        )
        
    def _classify(self, markdown):

        prompt = f"""
Classify this medical document.

Return ONLY JSON.

{{
    "document_type":"PRESCRIPTION | HOSPITAL_BILL | PHARMACY_BILL | LAB_REPORT | DIAGNOSTIC_REPORT | DISCHARGE_SUMMARY | DENTAL_REPORT | UNKNOWN",
    "confidence":0.95,
    "reasoning":"..."
}}

Document:
{markdown}
"""
        message = [
            {
                "role": "system",
                "content": prompt
            }
        ]
        res_llm = self.llm_client.call_llm(message)
        
        response = self.parse_llm_response(res_llm)
        print(response)

        return DocumentClassification.model_validate(
            response
        )
        
    def _extract(
        self,
        markdown,
        document_type
    ):  
        EXAMPLE_OUTPUT = """
{
    "document_type": "PHARMACY_BILL",
    "patient_name": "LALITKUMAR CHAUDHARI",
    "doctor_name": "Jitendra Kumar",
    "doctor_registration": null,
    "diagnosis": null,
    "hospital_name": null,
    "date": "2017-01-12",
    "total_amount": 5679.12,
    "medicines": [
        "Crocin 500mg"
    ],
    "line_items": [],
    "tests_ordered": [],
    "confidence": 0.95
}
"""
    
        prompt = f"""
You are an expert medical insurance document extraction agent.

Your job is to convert OCR/Docling output into structured claim information.

DOCUMENT TYPE:
{document_type}

EXTRACTION RULES:

1. Extract only information explicitly present in the document.
2. Correct obvious OCR mistakes when confidence is high.
3. If information is missing, return null.
4. Do not hallucinate values.
5. Convert dates into ISO format (YYYY-MM-DD) whenever possible.
6. Convert monetary amounts into float values.
7. Extract medicines separately when present.
8. Extract diagnostic tests separately when present.
9. Extract bill line items whenever available.
10. confidence must be between 0.0 and 1.0.

SPECIAL RULES:

PHARMACY_BILL:
- Extract medicines from bill items.
- Extract patient name.
- Extract doctor name.
- Calculate total_amount if explicitly available.
- If not visible, return null.

PRESCRIPTION:
- Extract diagnosis.
- Extract medicines.
- Extract doctor name.
- Extract doctor registration.
- Extract tests ordered.

LAB_REPORT:
- Extract test names into tests_ordered.
- Extract hospital/lab name.

DISCHARGE_SUMMARY:
- Extract diagnosis.
- Extract hospital.
- Extract admission/discharge dates if present.

OUTPUT REQUIREMENTS:

- Return ONLY valid JSON.
- Do NOT wrap response in markdown.
- Do NOT use ```json.
- Do NOT explain.
- Do NOT add notes.
- Do NOT add text before or after JSON.

JSON FORMAT EXAMPLE:

{EXAMPLE_OUTPUT}

DOCUMENT CONTENT:

{markdown}
"""
        message = [
            {
                "role": "system",
                "content": prompt
            }
        ]
        res = self.llm_client.call_llm(
            message
        )
        response = self.parse_llm_response(res)

        print(response)
        return ExtractedDocument.model_validate(
            response
        )
        
    def process_document(
        self,
        path: str
    ):
        # markdown = self._document_to_text(
        #     path
        # )
        markdown = None
        with open(path,"r",encoding="utf-8") as f:
            markdown = f.read()

        classification = self._classify(
            markdown
        )

        extracted = self._extract(
            markdown,
            classification.document_type
        )

        return {
                "classification": classification.model_dump(),
                "document": extracted.model_dump(),
                "markdown": markdown
        }