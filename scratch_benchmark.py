import time
import json
import orjson
from app.api.routes import get_user_dashboard_data, get_all_users
from app.database import clients_collection, users_collection

def benchmark_dashboard_data():
    # We will test get_user_dashboard_data for all clients (Admin view)
    client_match = {} 
    
    start_time = time.time()
    data = get_user_dashboard_data(client_match)
    end_time = time.time()
    
    # Serialize to test JSON stringification time without orjson
    start_json = time.time()
    json_str = json.dumps(data, default=str)
    end_json = time.time()
    
    # Serialize to test with orjson
    start_orjson = time.time()
    orjson_str = orjson.dumps(data, default=str)
    end_orjson = time.time()
    
    print(f"Aggregation & Python Processing Time: {(end_time - start_time) * 1000:.2f} ms")
    print(f"Standard JSON Serialization Time: {(end_json - start_json) * 1000:.2f} ms")
    print(f"ORJSON Serialization Time: {(end_orjson - start_orjson) * 1000:.2f} ms")
    print(f"Total Time (Standard): {(end_json - start_time) * 1000:.2f} ms")
    print(f"Total Time (ORJSON): {((end_time - start_time) + (end_orjson - start_orjson)) * 1000:.2f} ms")

if __name__ == "__main__":
    print("Running Benchmark...")
    benchmark_dashboard_data()
