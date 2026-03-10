"""Bearer token authentication for the API."""

import hmac
import os

from flask import jsonify, request

from otterwiki_api import api_bp


@api_bp.before_request
def check_api_key():
    # Health endpoint is exempt from auth
    if request.endpoint == "otterwiki_api.health":
        return None

    api_key = os.environ.get("OTTERWIKI_API_KEY")
    if not api_key:
        return jsonify({"error": "API key not configured on server"}), 500

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Missing or invalid Authorization header"}), 401

    token = auth_header[7:]  # len("Bearer ") == 7
    if not hmac.compare_digest(token, api_key):
        return jsonify({"error": "Invalid API key"}), 401

    return None
