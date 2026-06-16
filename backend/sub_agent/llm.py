import dotenv
import os
dotenv.load_dotenv()
import openai
import json

class LLMClient:
    def __init__(self):   
        self.api_key = os.getenv("GROQ_API_KEY")
        self.base_url = "https://api.groq.com/openai/v1"
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        if self.api_key is None:
            raise ValueError("GROQ_API_KEY not found in environment variables")
        self.client  = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        
    def call_llm(self,messages, temperature=0.7, **extra_args):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    **extra_args
                )
                return response.choices[0].message.content
            except Exception as e:
                print(f"Error calling LLM: {e}")
                return None
            
    def call_llm_json(
    self,
    messages,
    fallback=None,
    temperature=0.0
):
        fallback = fallback or {}

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                response_format={
                    "type": "json_object"
                }
            )

            content = (
                response.choices[0]
                .message
                .content
            )

            if not content:
                return fallback

            return json.loads(content)

        except Exception as e:

            print(
                f"Error calling LLM JSON: {e}"
            )

            return fallback