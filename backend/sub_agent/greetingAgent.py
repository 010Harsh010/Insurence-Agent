import json
import typing
import pydantic

import sub_agent.llm as llm


class GreetingResponse(pydantic.BaseModel):
    is_greeting: bool
    reply: typing.Optional[str] = None

class GreetingAgent:
    def __init__(self, client: llm.LLMClient):
        self.client = client

    def run(self, query: str) -> GreetingResponse:
        greet_prompt = [
            {
                "role": "system",
                "content": """
You are a Greeting Classifier.

Determine whether the user's message is a greeting.

Examples:
- hi
- hello
- good morning
- hey

Return ONLY valid JSON.

Greeting:
{
  "is_greeting": true,
  "reply": "Warm greeting..."
}

Not greeting:
{
  "is_greeting": false
}
"""
            },
            {
                "role": "user",
                "content": query
            }
        ]

        try:
            res_txt = self.client.call_llm(
                greet_prompt,
                temperature=0.0,
                response_format={"type": "json_object"}
            )

            data = json.loads(res_txt)
            return GreetingResponse.model_validate(data)

        except Exception as e:
            print(f"Greeting Agent Error: {e}")

            return GreetingResponse(
                is_greeting=False,
                reply="Sorry, I couldn't process your message."
            )