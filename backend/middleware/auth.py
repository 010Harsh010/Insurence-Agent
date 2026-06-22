import os
from functools import wraps
from flask import request, jsonify

def admin_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        password = request.headers.get("X-Admin-Password")

        if not password:
            return jsonify({
                "success": False,
                "message": "Password is required"
            }), 400

        if password != os.getenv("ADMIN_PASSWORD"):
            return jsonify({
                "success": False,
                "message": "Unauthorized"
            }), 401
            
        print("passowrd done")

        return f(*args, **kwargs)

    return decorated