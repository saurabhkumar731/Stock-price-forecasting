from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from pymongo.errors import ServerSelectionTimeoutError
from backend.config import Config

bcrypt = Bcrypt()

_client = MongoClient(Config.MONGO_URI, serverSelectionTimeoutMS=3000)
db = _client["stock_price"]
users_collection = db["users"]
chat_history_collection = db["chat_history"]

try:
    _client.admin.command("ping")
    users_collection.create_index("username", unique=True)
except ServerSelectionTimeoutError:
    raise SystemExit(
        f"\n[Ledger] Could not connect to MongoDB at {Config.MONGO_URI}\n"
        "  -> Is mongod running? Start it, or set MONGO_URI to your Atlas connection string.\n"
    )

