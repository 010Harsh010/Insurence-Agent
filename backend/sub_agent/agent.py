import sub_agent.llm as llm
from sub_agent import greetingAgent, gaurdrailAgent, routerAgent, policyAgent,text_sqlAgent

class AgentOrchestrator:
    def __init__(self):
        self.client = llm.LLMClient()
        self.greeting_agent = greetingAgent.GreetingAgent(self.client)
        self.guardrail_agent = gaurdrailAgent.GuardrailAgent(self.client)
        self.router_agent = routerAgent.RouterAgent()
        self.sql_agent = text_sqlAgent.PostgreSQLQueryAgent()
    
    def run(self, query,member_id="",claim_category=""):
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
            if member_id and claim_category:
                claim_bot = policyAgent.ClaimProcessingPipeline(
                    member_id=member_id,
                    claim_category=claim_category,
                    output_dir="./output"
                )
                result = claim_bot.run()
                Response["ClaimAgent"]  = result
        elif router_response.route == routerAgent.RouteType.QUESTION_ANSWERING:
            response = self.sql_agent.run(query)
            Response["Answer"] = response
        else:
            raise ValueError(f"Unknown route: {router_response.route}")
        
        return Response