import jwt
import datetime
from functools import wraps
from flask import request, jsonify, g
from backend.config import Config


def create_token(user_id: str, username: str) -> str:
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=Config.JWT_EXPIRY_HOURS),
        "iat": datetime.datetime.utcnow(),
    }
    return jwt.encode(payload, Config.JWT_SECRET, algorithm="HS256")


def decode_token(token: str):
    try:
        return jwt.decode(token, Config.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def login_required(f):
    """Reads the JWT from the httpOnly cookie, validates it, and attaches
    the current user to `g.user`. Returns 401 if missing/invalid/expired."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = request.cookies.get(Config.COOKIE_NAME)
        if not token:
            return jsonify({"error": "Not authenticated"}), 401
        payload = decode_token(token)
        if not payload:
            return jsonify({"error": "Session expired, please log in again"}), 401
        g.user = payload
        return f(*args, **kwargs)
    return wrapper
