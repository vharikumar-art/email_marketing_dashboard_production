import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import settings_collection

def add_default_payment_methods():
    print("Adding default payment methods...")
    default_methods = ["Bank Transfer", "Google Pay (GPay)", "PhonePe", "PayPal", "Stripe", "Cash"]
    
    settings_collection.update_one(
        {"key": "lookup_settings"},
        {"$addToSet": {"payment_method": {"$each": default_methods}}},
        upsert=True
    )
    print("Payment methods added successfully.")

if __name__ == "__main__":
    add_default_payment_methods()
