import os
from flask import Flask, send_from_directory
from flask_cors import CORS
from backend.extensions import bcrypt
from backend.routes.auth import auth_bp
from backend.routes.predict import predict_bp
from backend.routes.chatbot import chatbot_bp

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")


def create_app():
    app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
    CORS(app, supports_credentials=True)
    bcrypt.init_app(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(predict_bp)
    app.register_blueprint(chatbot_bp)

    # Serve the static HTML/CSS/JS pages directly from /frontend
    @app.get("/")
    def landing():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:path>")
    def static_pages(path):
        return send_from_directory(FRONTEND_DIR, path)

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
