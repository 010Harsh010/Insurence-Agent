from enum import Enum
from pathlib import Path
from pydantic import BaseModel, Field
from dataclasses import dataclass

from langchain_docling.loader import DoclingLoader
from langchain_docling.loader import ExportType
import sub_agent.llm
import re
from metrics import DOCUMENTS_PROCESSED

import json

class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    PHARMACY_BILL = "PHARMACY_BILL"
    LAB_REPORT = "LAB_REPORT"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    CONSULTATION= "CONSULTATION"
    DENTAL_REPORT = "DENTAL_REPORT"
    UNKNOWN = "UNKNOWN"
    
REQUIRED_FIELDS = {
    DocumentType.HOSPITAL_BILL: [
        "hospital_name",
        "date",
    ],

    DocumentType.PRESCRIPTION: [
        "patient_name",
        "diagnosis",
    ],

    DocumentType.DISCHARGE_SUMMARY: [
        "patient_name",
        "hospital_name",
        "doctor_name",
        "diagnosis",
        "date"
    ],

    DocumentType.LAB_REPORT: [
        "patient_name",
        "hospital_name",
        "tests_ordered",
        "date"
    ],

    DocumentType.CONSULTATION: [
        "patient_name",
        "doctor_name",
        "diagnosis",
        "date"
    ]
}


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

@dataclass
class ValidationResult:
    is_valid: bool
    missing_fields: list[str]
    
    
from dataclasses import dataclass
import cv2
import numpy as np


@dataclass
class QualityResult:
    score: float
    quality: str

    blur_score: float
    contrast_score: float
    brightness_score: float
    resolution_score: float

    width: int
    height: int


class QualityAgent:

    def __init__(self):
        pass

    def _blur_score(
        self,
        gray: np.ndarray
    ) -> float:

        variance = cv2.Laplacian(
            gray,
            cv2.CV_64F
        ).var()

        if variance >= 500:
            return 100

        if variance >= 200:
            return 80

        if variance >= 100:
            return 60

        if variance >= 50:
            return 40

        return 10

    def _contrast_score(
        self,
        gray: np.ndarray
    ) -> float:

        std = gray.std()

        if std >= 70:
            return 100

        if std >= 50:
            return 80

        if std >= 35:
            return 60

        if std >= 20:
            return 40

        return 10

    def _brightness_score(
        self,
        gray: np.ndarray
    ) -> float:

        mean = gray.mean()

        if 80 <= mean <= 180:
            return 100

        if 60 <= mean <= 200:
            return 70

        if 40 <= mean <= 220:
            return 50

        return 20

    def _resolution_score(
        self,
        width: int,
        height: int
    ) -> float:

        pixels = width * height

        if pixels >= 3000000:
            return 100

        if pixels >= 1500000:
            return 80

        if pixels >= 800000:
            return 60

        if pixels >= 400000:
            return 40

        return 10

    def check(
        self,
        image_path: str
    ) -> QualityResult:

        image = cv2.imread(image_path)

        if image is None:
            raise ValueError(
                f"Unable to read image: {image_path}"
            )

        height, width = image.shape[:2]

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY
        )

        blur_score = self._blur_score(
            gray
        )

        contrast_score = self._contrast_score(
            gray
        )

        brightness_score = self._brightness_score(
            gray
        )

        resolution_score = self._resolution_score(
            width,
            height
        )

        final_score = (
            blur_score * 0.40 +
            contrast_score * 0.20 +
            brightness_score * 0.10 +
            resolution_score * 0.30
        )

        if final_score >= 75:
            quality = "GOOD"

        elif final_score >= 50:
            quality = "OK"

        else:
            quality = "POOR"

        return QualityResult(
            score=round(final_score, 2),
            quality=quality,

            blur_score=round(
                blur_score,
                2
            ),

            contrast_score=round(
                contrast_score,
                2
            ),

            brightness_score=round(
                brightness_score,
                2
            ),

            resolution_score=round(
                resolution_score,
                2
            ),

            width=width,
            height=height
        )
        
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
    
    def validate_document(
        self,
    document: ExtractedDocument
) -> ValidationResult:

        required_fields = REQUIRED_FIELDS.get(
            document.document_type,
            []
        )

        missing_fields = []

        for field_name in required_fields:

            value = getattr(
                document,
                field_name,
                None
            )

            if value is None:
                missing_fields.append(field_name)
                continue

            if isinstance(value, str) and not value.strip():
                missing_fields.append(field_name)

            elif isinstance(value, list) and len(value) == 0:
                missing_fields.append(field_name)

        return ValidationResult(
            is_valid=len(missing_fields) == 0,
            missing_fields=missing_fields
        )

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
        # print(response)

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

        # print(response)
        return ExtractedDocument.model_validate(
            response
        )
        
    def process_document(
        self,
        path: str
    ):
            suffix = Path(path).suffix.lower()
            quality_result = None
            if suffix != ".pdf":
                print("Start Quality")
                agent = QualityAgent()

                quality_result = agent.check(path)
                
                print(f"Quality Check Result: {quality_result}")

                if quality_result.quality == "POOR" or quality_result.score < 70 or quality_result.blur_score>50:
                    raise ValueError(
                        "Document quality is Poor. Please upload a Clear Document."
                    )
            # print("Start Markdown")
            markdown = self._document_to_text(
                path
            )
            
            # print(markdown)

            classification = self._classify(
                markdown
            )
            
            DOCUMENTS_PROCESSED.labels(classification.document_type).inc()
        

            extracted = self._extract(
                markdown,
                classification.document_type
            )
            
            result = self.validate_document(extracted)

            # print(result.is_valid)
            # print(result.missing_fields)
            if not result.is_valid:
                raise ValueError(f"Required Fields Missing: {result.missing_fields}")
            
            res =  {
                    "classification": classification.model_dump(mode="json"),
                    "document": extracted.model_dump(mode="json"),                    
                    "markdown": markdown
            }
        
            if quality_result:
                res["Quality"] = quality_result.model_dump(mode="json")
                
            return res