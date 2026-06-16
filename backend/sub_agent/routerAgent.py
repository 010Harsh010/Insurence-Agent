from enum import Enum
from pydantic import BaseModel
import sub_agent.llm as llm


class RouteType(str, Enum):
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
    CLAIM_PROCESSING = "CLAIM_PROCESSING"
    QUESTION_ANSWERING = "QUESTION_ANSWERING"

class RouterResponse(BaseModel):
    route: RouteType

class RouterAgent:
    
    def __init__(self):
        self.client = llm.LLMClient()

    SYSTEM_PROMPT = """
    You are an Insurance Claim Router Agent.

    Classify the user query into exactly one route.

    DOCUMENT_UPLOAD
    - User wants to upload/add/submit documents.
    - User mentions invoice, prescription, bill,
      discharge summary, report, receipt.
    - User says:
      "I want to upload documents"
      "Add bill to my claim"
      "Submit medical report"

    CLAIM_PROCESSING
    - User wants to create, track,
      continue or process a claim.
    - User says:
      "File a claim"
      "Create claim"
      "Start reimbursement"
      "Check my claim status"

    QUESTION_ANSWERING
    - User is asking information.
    - User says:
      "What is covered?"
      "How much deductible?"
      "Is consultation covered?"
      "What documents are required?"

    Return JSON:
    {
      "route": "..."
    }
    """

    def route(self, query: str) -> RouterResponse:
        messages=[
                        {
                            "role": "system",
                            "content": self.SYSTEM_PROMPT
                        },
                        {
                            "role": "user",
                            "content": query
                        }
                    ]
        response = self.client.call_llm_json(
            messages=messages
        )
        
        RouterResponse.model_validate(response)

        return RouterResponse(
            route=RouteType(response["route"])
        )