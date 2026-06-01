import os
import sys

# Add the project root to sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import settings_collection

def add_mock_data():
    mock_bank_accounts = [
        {
            "account_number": "123456789",
            "bank_name": "Chase Bank",
            "handler_name": "Alice Smith",
            "ifsc_code": "CHAS0001"
        },
        {
            "account_number": "987654321",
            "bank_name": "Bank of America",
            "handler_name": "Bob Jones",
            "ifsc_code": "BOFA0002"
        },
        {
            "account_number": "112233445",
            "bank_name": "Wells Fargo",
            "handler_name": "Charlie Brown",
            "ifsc_code": "WELL0003"
        }
    ]

    print("Adding mock bank accounts to settings...")
    
    # Add each mock account to the lookup_settings
    for account in mock_bank_accounts:
        result = settings_collection.update_one(
            {"key": "lookup_settings"},
            {"$addToSet": {"bank_account": account}},
            upsert=True
        )
        if result.modified_count > 0 or result.upserted_id:
            print(f"Added: {account['bank_name']} - {account['account_number']}")
        else:
            print(f"Already exists (or no change): {account['bank_name']} - {account['account_number']}")
            
    print("Mock data injection complete!")

if __name__ == "__main__":
    add_mock_data()
