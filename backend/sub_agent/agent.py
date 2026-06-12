import sub_agent.llm as llm
from sub_agent import greetingAgent, gaurdrailAgent

class AgentOrchestrator:
    def __init__(self,client: llm.LLMClient):
        self.greeting_agent = greetingAgent.GreetingAgent(client)
        self.guardrail_agent = gaurdrailAgent.GuardrailAgent(client)
    
    def run(self, query):
        if not query:
            raise ValueError("Query cannot be empty")
        
        Response = []
        

        
        guardrail_response = self.guardrail_agent.run(query)
        Response.append(guardrail_response.reply)
        if not guardrail_response.allowed:
            return Response
        
        greeting_response = self.greeting_agent.run(query)
        if greeting_response.is_greeting:
            Response.append(greeting_response.reply)
            return Response

        return Response
    
    
llm_client = llm.LLMClient()
orchestrator = AgentOrchestrator(llm_client)