from flask import Blueprint, request, jsonify, make_response
from bson.objectid import ObjectId
from backend.extensions import bcrypt, users_collection
from backend.auth_utils import create_token, login_required
from backend.config import Config

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/signup")
def signup():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not email or not password:
        return jsonify({"error": "username, email and password are required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if users_collection.find_one({"username": username}):
        return jsonify({"error": "Username already taken"}), 409

    hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
    result = users_collection.insert_one({
        "username": username,
        "email": email,
        "password_hash": hashed_pw,
    })

    token = create_token(str(result.inserted_id), username)
    resp = make_response(jsonify({"message": "Account created", "username": username}))
    resp.set_cookie(Config.COOKIE_NAME, token, httponly=True, samesite="Lax", max_age=Config.JWT_EXPIRY_HOURS * 3600)
    return resp, 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = users_collection.find_one({"username": username})
    if not user or not bcrypt.check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    token = create_token(str(user["_id"]), username)
    resp = make_response(jsonify({"message": "Logged in", "username": username}))
    resp.set_cookie(Config.COOKIE_NAME, token, httponly=True, samesite="Lax", max_age=Config.JWT_EXPIRY_HOURS * 3600)
    return resp, 200


@auth_bp.post("/logout")
def logout():
    resp = make_response(jsonify({"message": "Logged out"}))
    resp.delete_cookie(Config.COOKIE_NAME)
    return resp, 200


@auth_bp.get("/me")
@login_required
def me():
    from flask import g
    return jsonify({"username": g.user["username"]}), 200
