import flask
import flask_cors
import db.db as db
from middleware.auth import admin_auth
import sub_agent.policyAgent
from flask import Flask, request, jsonify
import os
import json
import shutil
from test.test import process
import uuid

app = flask.Flask(__name__)

flask_cors.CORS(app)

data_loader = None
document_agents = None
orchestrator = None

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
        print(response.get("Answer"))
        return {
            "ui": {
                "type": "answer",
                "message": response.get("Answer").get("data")
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

    upload_folder = os.path.join("documents", member_id)

    os.makedirs(upload_folder, exist_ok=True)
    filepath = os.path.join(upload_folder, file.filename)
    file.save(filepath)

    try:
        response = document_agents.process_document(filepath)

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
        print(e)
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
    }, 200

@app.route("/chat", methods=["GET"])
def chat():
    try:
        query = flask.request.args.get("query", type=str)
        member_id = flask.request.args.get("member_id", type=str)
        claim_category = flask.request.args.get("claim_category", type=str)

        if not query:
            return {
                "status": 400,
                "message": "Query is required"
            }, 400

        response = orchestrator.run(query, member_id, claim_category)

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
    return {"status": 200, "message": "Backend is healthy"}

# ── Add Policy ────────────────────────────────────────────────────────────────
@app.route("/addPolicy", methods=["GET", "POST"])
@admin_auth
def addPolicy():
    # Accept either a JSON file upload (multipart) or raw JSON body
    if request.files.get("policy"):
        f = request.files["policy"]
        try:
            policy = json.load(f)
        except Exception as e:
            return jsonify({"success": False, "message": f"Invalid JSON file: {e}"}), 400
    else:
        data = flask.request.get_json() or {}
        policy = data.get("policy")

    if not policy:
        return jsonify({"success": False, "message": "Policy data is required"}), 400

    res = data_loader.load_policy_file(policy)
    if not res:
        return jsonify({"success": False, "message": "Policy could not be inserted"}), 404

    return jsonify({"success": True, "message": "Policy added successfully"}), 200

@app.route("/claimPolicy", methods=["GET", "POST"])
def claimPolicy():
    try:
        agent = sub_agent.policyAgent.PolicyClaim()
        emp = flask.request.args.get("employeeID", type=str)
        category = flask.request.args.get("category", type=str)
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
            "status": 404,
            "message": e
        }

# ── Update Claim ──────────────────────────────────────────────────────────────
@app.route("/updateClaim", methods=["POST"])
@admin_auth
def update_claim():
    data = request.get_json() or {}

    claim_status = data.get("claim_status")
    claim_id = data.get("claim_id")
    approve_amount = data.get("approve_amount") or 0
    print("Update Status", claim_status, "\n claim id", claim_id)
    if not (claim_status and claim_id):
        return jsonify({
            "success": False,
            "message": "Missing Details",
        }), 404
    response = data_loader.updatePolicyClaim(
        claim_id=claim_id,
        claim_status=claim_status,
        approve_amount=approve_amount
    )
    print("Response", response)
    status_code = 200 if response["status"] == "UPDATED" else 400
    return jsonify(response), status_code

# ── Reset Database ────────────────────────────────────────────────────────────
@app.route("/resetDB", methods=["POST"])
@admin_auth
def reset_db():
    try:
        database = db.Database()
        message = database.reset_all_tables()
        return jsonify({"success": True, "message": "Database reset successfully"}), 200
    except Exception as e:
        print(f"Reset DB error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

# ── Delete Member Documents ───────────────────────────────────────────────────
@app.route("/member/<member_id>/documents", methods=["DELETE"])
def delete_member_documents(member_id):
    if not member_id:
        return jsonify({"success": False, "message": "member_id is required"}), 400

    member_folder = os.path.join("documents", member_id)

    if not os.path.exists(member_folder):
        return jsonify({
            "success": False,
            "message": f"No documents found for member {member_id}"
        }), 404

    try:
        shutil.rmtree(member_folder)
        return jsonify({
            "success": True,
            "message": f"All documents for member {member_id} deleted successfully"
        }), 200
    except Exception as e:
        print(f"Delete documents error: {e}")
        return jsonify({"success": False, "message": str(e)}), 500

# ── Run Tests ─────────────────────────────────────────────────────────────────
@app.route("/test", methods=["POST"])
def run_tests():
    try:
        results = process()
        return jsonify({
            "success": True,
            "results": results,
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to run tests: {str(e)}"}), 500

# ── Fetch existing test results (no re-run) ────────────────────────────────────
@app.route("/test", methods=["GET"])
def get_test_results():
    result_file = os.path.join(os.path.dirname(__file__), "test", "result.json")
    if not os.path.exists(result_file):
        return jsonify({"success": False, "message": "No test results found. Run tests first."}), 404
    with open(result_file, "r", encoding="utf-8") as f:
        results = json.load(f)
    return jsonify({"success": True, "results": results}), 200

if __name__ == "__main__":
    try:
        
        # Step 1
        db.Database().initialize_schema()
        
        # Step 2
        from document_agent.document_identifier import DocumentAgent
        import services.data_ingestion
        data_loader = services.data_ingestion.PolicyLoader()
        document_agents = DocumentAgent()
        
        # Step 3
        from sub_agent.agent import AgentOrchestrator
        orchestrator = AgentOrchestrator()
        
        # Step 3
        app.run(debug=True, port=8000)
    except Exception as e:
        print(f"Error initializing database: {e}")