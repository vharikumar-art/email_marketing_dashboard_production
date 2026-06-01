from pymongo import MongoClient
from app.config import MONGO_URI, DB_NAME

if not MONGO_URI:
    raise RuntimeError("MONGO_URI environment variable is required")
if not DB_NAME:
    raise RuntimeError("DB_NAME environment variable is required")

client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[DB_NAME]

users_collection = db["users"]
tokens_collection = db["tokens"]
clients_collection = db["clients"]
orders_collection = db["orders"]
manuscripts_collection = db["manuscripts"]
payments_collection = db["payments"]
payment_history_collection = db["payment_history"]
otps_collection = db["otps"]
settings_collection = db["settings"]
bank_accounts_collection = db["bank_accounts"]
audit_logs_collection = db["audit_logs"]

def ensure_indexes():
    """Create MongoDB indexes once during application startup."""
    users_collection.create_index("email", unique=True)
    users_collection.create_index("full_name")
    users_collection.create_index("role")
    clients_collection.create_index("client_id", unique=True)
    clients_collection.create_index("client_handler")
    orders_collection.create_index("client_id")
    orders_collection.create_index("order_id", unique=True)
    orders_collection.create_index("reference_id")
    orders_collection.create_index("s_no")
    orders_collection.create_index("order_date")
    orders_collection.create_index([("client_id", 1), ("order_id", 1)])
    payments_collection.create_index([("order_id", 1), ("phase", 1)])
    payments_collection.create_index("client_id")
    payments_collection.create_index("order_id")
    payments_collection.create_index("phase")
    payment_history_collection.create_index("client_id")
    payment_history_collection.create_index("order_id")
    payment_history_collection.create_index("payment_date")
    tokens_collection.create_index("token", unique=True)
    tokens_collection.create_index("created_at", expireAfterSeconds=36000)
    audit_logs_collection.create_index([("document_id", 1), ("field_name", 1)])
    audit_logs_collection.create_index("collection_name")
    audit_logs_collection.create_index("edited_at")
