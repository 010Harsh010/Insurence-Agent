import flask
import flask_cors

app = flask.Flask(__name__)

flask_cors.CORS(app)

@app.route("/claim",methods=["POST"])
def claim():
    res = {
        "status": 200,
        "message": "Claim processed successfully"
    }
    return res

@app.route("/health")
def health():
    res = {
        "status": 200,
        "message": "Backend is healthy"
    }
    return res 

if __name__ == "__main__":
    app.run(debug=True, port=8000)