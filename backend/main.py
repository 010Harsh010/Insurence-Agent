import flask
import flask_cors
from sub_agent.agent import orchestrator

app = flask.Flask(__name__)

flask_cors.CORS(app)

@app.route("/claim",methods=["POST"])
def claim():
    res = {
        "status": 200,
        "message": "Claim processed successfully"
    }
    return res

@app.route("/chat",methods=["GET"])
def chat():
    try:
        query = flask.request.args.get("query",type=str)
        if not query:
            return {
                "status": 400,
                "message": "Query is required"
            }, 400
            
        # Orchestrate the agents
        response = orchestrator.run(query)
        res = {
            "status": 200,
            "data": response
        }
        return res
    except Exception as e:
        return {
            "status": 500,
            "message": f"An error occurred: {str(e)}"
        }
    

@app.route("/health")
def health():
    res = {
        "status": 200,
        "message": "Backend is healthy"
    }
    return res 

if __name__ == "__main__":
    app.run(debug=True, port=8000)