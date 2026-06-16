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
        
        Response = {}
        
        greeting_response = self.greeting_agent.run(query)
        if greeting_response.is_greeting:
            Response["Greeting"] =  greeting_response.reply
            return Response
        
        guardrail_response = self.guardrail_agent.run(query)
        if not guardrail_response.allowed:
            Response["Garudrail"] = guardrail_response.reply
            return Response
        
        

        router_response = self.router_agent.route(query)
        Response["Router"] = router_response.route
        
        if router_response.route == routerAgent.RouteType.CLAIM_PROCESSING:
            claim_bot = policyAgent.ClaimProcessingPipeline(
                member_id="EMP001",
                claim_category="CONSULTATION",
                output_dir="./output"
            )
            result = claim_bot.run()
            Response["ClaimAgent"]  = result
        elif router_response.route == routerAgent.RouteType.QUESTION_ANSWERING:
            pass
        else:
            raise ValueError(f"Unknown route: {router_response.route}")
        
        return Response
    
    
llm_client = llm.LLMClient()
orchestrator = AgentOrchestrator(llm_client)