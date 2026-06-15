import flask
import flask_cors
from sub_agent.agent import orchestrator
# import db.db as db
import services.data_ingestion
import document_agent.document_identifier

app = flask.Flask(__name__)

flask_cors.CORS(app)

data_loader = services.data_ingestion.PolicyLoader()
document_agents = document_agent.document_identifier.DocumentAgent()

@app.route("/claim",methods=["POST"])
def claim():
    res = {
        "status": 200,
        "message": "Claim processed successfully"
    }
    return res

@app.route("/upload",methods=["POST","GET"])
def upload():
    txt = document_agent.document_identifier.docling_document_to_text("C://Users//hs250//vscode//BTP//Plum Assignment - 12-04-2026//backend//document_agent//medicine_bill.png")
    with open("docking_output.md","w", encoding="utf-8") as f:
        f.write(txt)
    return txt

@app.route("/extract",methods=["POST","GET"])
def extract():
    try:
        path = r"C:\Users\hs250\vscode\BTP\Plum Assignment - 12-04-2026\backend\output\docling_medicine_bill.md"
        response = document_agents.process_document(path)
        return {
            "status": 200,
            "message": "Feature extracted successfully",
            "data": response
        }
    except Exception as e:
        return {
            "status": 500,
            "message": f"An error occurred: {str(e)}"
        }
        
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

@app.route("/addPolicy",methods=["GET","POST"])
def addPolicy():
    PATH="C:/Users/hs250/vscode/BTP/Plum Assignment - 12-04-2026/policy_terms.json"
    data_loader.load_policy_file(PATH)
    res = {
        "status": 200,
        "message": "Policy added successfully"
    }
    return res 
    

if __name__ == "__main__":
    try:
        # db.Database().initialize_schema()
        app.run(debug=True, port=8000)
    except Exception as e:
        print(f"Error initializing database: {e}")