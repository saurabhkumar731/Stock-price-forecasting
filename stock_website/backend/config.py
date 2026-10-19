import os
from dotenv import load_dotenv
load_dotenv()
class Config:
    MONGO_URI = os.environ.get("MONGO_URI")
    JWT_SECRET = os.environ.get("JWT_SECRET", "change-this-secret-in-production")
    JWT_EXPIRY_HOURS = 24
    OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1.11434")
    MODELS_DIR = os.environ.get("MODELS_DIR", os.path.join(os.path.dirname(__file__), "..", "models"))
    COOKIE_NAME = "stock_app_token"
