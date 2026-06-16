import flask
import flask_cors
from sub_agent.agent import orchestrator
from sub_agent.decision_maker import adjudicate_claim
import db.db as db
import services.data_ingestion
import document_agent.document_identifier
import sub_agent.policyAgent

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


@app.route("/adjudicate", methods=["POST"])
def adjudicate():
    """
    Full 14-step AI adjudication pipeline (document-driven).

    Expected JSON body:
    {
      "member_id": "EMP001"
    }

    Documents are auto-loaded from backend/documents/{member_id}/.
    Everything else (policy_id, claim_category, claimed_amount,
    treatment_date, hospital_name) is derived automatically from
    the member's DB record and the extracted document data.
    """
    try:
        body = flask.request.get_json(force=True)
        if not body:
            return flask.jsonify({"status": 400, "message": "Request body is required"}), 400

        if "member_id" not in body:
            return flask.jsonify({
                "status": 400,
                "message": "Missing required field: member_id"
            }), 400

        # Supports two calling styles:
        #   NEW → { "member_id": "EMP001", "documents": [doc1, doc2, ...] }
        #   OLD → { "member_id": "EMP001", "document": doc1, "extra_documents": [doc2] }
        if "documents" in body:
            result = adjudicate_claim(
                member_id=body["member_id"],
                documents=body["documents"],         # flat array — all docs together
            )
        else:
            result = adjudicate_claim(
                member_id=body["member_id"],
                document_agent_response=body.get("document"),
                extra_documents=body.get("extra_documents") or [],
            )

        return flask.jsonify({
            "status":  200,
            "message": "Adjudication complete",
            "data":    result.model_dump(mode="json"),
        })

    except Exception as e:
        return flask.jsonify({
            "status":  500,
            "message": f"Adjudication pipeline error: {str(e)}"
        }), 500

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
    res = data_loader.load_policy_file(PATH)
    if not res:
        res = {
            "status": 404,
            "message": "Policy not Insert"
        }
        return res
    
    res = {
        "status": 200,
        "message": "Policy added successfully"
    }
    return res 
    
    
@app.route("/checks",methods=["GET","POST"])
def checks():
    try:
        agent = sub_agent.policyAgent.PolicyClaim()
        emp = flask.request.args.get("emp",type=str)
        if not emp:
            return {
                "status": 400,
                    "message": "Emp ID is required"
            }, 400
        output = agent.run(member=emp)
        return {
            "status": 200,
            "data": output.dict()
        }
    except Exception as e:
        print(e)
        return {
            "status":404,
            "message": e
        }

if __name__ == "__main__":
    try:
        db.Database().initialize_schema()
        app.run(debug=True, port=8000)
    except Exception as e:
        print(f"Error initializing database: {e}")