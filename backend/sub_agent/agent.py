import sub_agent.llm as llm
from sub_agent import greetingAgent, gaurdrailAgent, routerAgent, policyAgent

class AgentOrchestrator:
    def __init__(self,client: llm.LLMClient):
        self.greeting_agent = greetingAgent.GreetingAgent(client)
        self.guardrail_agent = gaurdrailAgent.GuardrailAgent(client)
        self.router_agent = routerAgent.RouterAgent()
    
    def run(self, query):
        if not query:
            raise ValueError("Query cannot be empty")
        
        Response = []
        
        # guardrail_response = self.guardrail_agent.run(query)
        # Response.append(guardrail_response.reply)
        # if not guardrail_response.allowed:
        #     return Response
        
        # greeting_response = self.greeting_agent.run(query)
        # if greeting_response.is_greeting:
        #     Response.append(greeting_response.reply)
        #     return Response

        # router_response = self.router_agent.route(query)
        # Response.append(router_response.route)
        
        # if router_response.route == routerAgent.RouteType.DOCUMENT_UPLOAD:
        #     pass
        # elif router_response.route == routerAgent.RouteType.CLAIM_PROCESSING:
        claim_bot = policyAgent.ClaimProcessingPipeline(
            member_id="EMP002",
            claim_category="CONSULTATIO",
            output_dir="./output"
        )
        result = claim_bot.run()
        Response.append(result)
        # elif router_response.route == routerAgent.RouteType.QUESTION_ANSWERING:
        #     pass
        # else:
        #     raise ValueError(f"Unknown route: {router_response.route}")
        
        return Response
    
    
llm_client = llm.LLMClient()
orchestrator = AgentOrchestrator(llm_client)