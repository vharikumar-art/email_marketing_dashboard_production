import os
import sys

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import settings_collection

def remove_old_accounts():
    print("Removing old string accounts...")
    result = settings_collection.update_one(
        {"key": "lookup_settings"},
        {"$pull": {"bank_account": {"$in": ["963852741789", "78965432198", "987321654321"]}}}
    )
    print(f"Modified count: {result.modified_count}")

if __name__ == "__main__":
    remove_old_accounts()
