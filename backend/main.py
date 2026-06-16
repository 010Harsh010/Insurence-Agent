import flask
import flask_cors
from sub_agent.agent import orchestrator
from sub_agent.decision_maker import adjudicate_claim
import db.db as db
import services.data_ingestion
from document_agent.document_identifier import DocumentAgent
import sub_agent.policyAgent
from flask import Flask, request
import os
import json

app = flask.Flask(__name__)

flask_cors.CORS(app)

data_loader = services.data_ingestion.PolicyLoader()
document_agents = DocumentAgent()


def response_cleaner(response):

    if response.get("Greeting"):
        return {
            "ui": {
                "type": "message",
                "message": response["Greeting"]
            }
        }

    if response.get("Garudrail"):
        return {
            "ui": {
                "type": "message",
                "message": response["Garudrail"]
            }
        }

    if response.get("Router") == "CLAIM_PROCESSING":

        claim = response.get("ClaimAgent", {})

        if claim.get("decision"):
            return {
                "ui": {
                    "type": "decision",
                    "message": claim["decision"]
                }
            }

        if claim.get("error"):
            return {
                "ui": {
                    "type": "error",
                    "message": claim.get("error_message")
                }
            }

    if response.get("Router") == "QUESTION_ANSWERING":
        return {
            "ui": {
                "type": "answer",
                "message": response.get("Answer")
            }
        }

    return {
        "ui": {
            "type": "error",
            "message": "Unable to process response"
        }
    }
    
    
@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get("document")
    member_id = request.args.get("member_id")

    if not member_id:
        return {"error": "member_id is required"}, 400

    if not file or file.filename == "":
        return {"error": "No file selected"}, 400

    upload_folder = os.path.join(
        "documents",
        member_id
    )
    
    print(f"Upload folder {upload_folder}")

    os.makedirs(upload_folder, exist_ok=True)
    filepath = os.path.join(upload_folder, file.filename)
    file.save(filepath)
    
    print("File Uploaded")

    try:
        response = document_agents.process_document(
            filepath
        )
        print("Process Document")

        json_path = os.path.join(
            upload_folder,
            f"{os.path.splitext(file.filename)[0]}.json"
        )
        md_path = os.path.join(
            upload_folder,
            f"{os.path.splitext(file.filename)[0]}.md"
        )
                
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(response["markdown"])

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(response, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        return {
            "filename": file.filename,
            "path": filepath,
            "error": str(e)
        }, 500

    return {
        "filename": file.filename,
        "path": filepath,
        "markdown_path": md_path,
        "message": "File uploaded successfully"
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
        
        clean_res = response_cleaner(response)
        clean_res["data"] = response
        res = {
            "status": 200,
            "data": clean_res
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
    
@app.route("/claimPolicy",methods=["GET","POST"])
def claimPolicy():
    try:
        agent = sub_agent.policyAgent.PolicyClaim()
        emp = flask.request.args.get("employeeID",type=str)
        category = flask.request.args.get("category",type=str)
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