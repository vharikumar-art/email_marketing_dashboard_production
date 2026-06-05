# Detailed Project Architecture: Email Marketing Dashboard

## 1. System Overview
The Email Marketing Dashboard is a robust backend system designed to manage clients, orders, multi-phase payments, and system configurations. It is built using a modern, asynchronous Python stack optimized for high performance, scalability, and ease of maintenance.

---

## 2. Technology Stack
- **Language:** Python 3.9+
- **Web Framework:** [FastAPI](https://fastapi.tiangolo.com/) - Chosen for its high performance, automatic interactive API documentation (Swagger/OpenAPI), and native support for asynchronous programming.
- **Database:** [MongoDB](https://www.mongodb.com/) via `pymongo` - A flexible NoSQL database allowing dynamic schema evolution.
- **Data Validation & Serialization:** [Pydantic](https://docs.pydantic.dev/) - Enforces strict typing, validates incoming request bodies, and shapes outgoing JSON responses.
- **Authentication & Authorization:** JWT (JSON Web Tokens) combined with Bcrypt for password hashing.
- **Server/Deployment:** Uvicorn (ASGI server) serving the FastAPI application.
- **Email Delivery:** `aiosmtplib` - Asynchronous SMTP client used primarily for sending secure One-Time Passwords (OTPs).

---

## 3. Directory Structure

```text
email_dashboard_production/
├── app/
│   ├── api/
│   │   ├── router.py         # Aggregates all route modules
│   │   └── routes.py         # Detailed endpoint definitions (Auth, Users, Clients, Orders, Payments, Settings)
│   ├── __init__.py
│   ├── auth.py               # JWT logic, password hashing, role-based dependencies
│   ├── cache.py              # In-memory caching logic (dashboard metrics, exchange rates)
│   ├── config.py             # Environment variables and application configuration
│   ├── currency_converter.py # Utility functions for USD/INR and other currency conversions
│   ├── database.py           # MongoDB connection setup and index creation
│   ├── main.py               # Application entry point, middleware, exception handlers
│   └── schemas.py            # Pydantic models for request/response validation
├── static/                   # Static assets and user uploads (profile photos, receipts)
│   └── uploads/
├── project_architecture.md   # This document
└── api_documentation_postman.md
```

---

## 4. Core Application Components (`app/main.py`)

### 4.1. Application Entry Point
`create_app()` initializes the FastAPI application. It is responsible for wiring up middleware, static files, and the main API router.

### 4.2. Middleware
- **CORSMiddleware:** Configured to allow specific origins (`http://localhost:5173`, etc.) ensuring the frontend React/Vite application can communicate securely with the backend.
- **GZipMiddleware:** Compresses responses larger than 1000 bytes to reduce bandwidth and improve load times.
- **PerformanceMiddleware:** A custom `BaseHTTPMiddleware` that tracks request processing times and logs warnings for slow requests (e.g., > 0.5s or > 1.0s).

### 4.3. Exception Handling
Custom global exception handlers override the default FastAPI behavior to ensure that every error (whether a planned `HTTPException` or an unexpected `Exception`) returns a standardized JSON structure:
```json
{
  "status_code": 400,
  "status": "error",
  "message": "Specific error detail",
  "data": null
}
```

---

## 5. Database Architecture (`app/database.py`)

MongoDB is utilized without an ODM (like Beanie or MongoEngine), relying directly on `pymongo` dictionaries for maximum speed. Indexes are actively managed via the `ensure_indexes()` startup event.

### 5.1. Collections and Indexes
- **`users`**: Stores system users. Indexed by `email` (unique), `full_name`, and `role`.
- **`clients`**: Stores client profiles. Indexed by `client_id` (unique) and `client_handler`.
- **`orders`**: Stores order details. Indexed by `client_id`, `order_id` (unique), `reference_id`, `s_no`, and `order_date`.
- **`payments` / `payment_history`**: Tracks multi-phase transactions. Compound indexes on `[("order_id", 1), ("phase", 1)]` ensure efficient querying of a specific payment phase for a specific order.
- **`tokens`**: Manages active JWT sessions. Indexed on `created_at` with a TTL (Time-To-Live) of 36000 seconds for automatic token expiration cleanup.
- **`otps`**: Stores temporary codes for Admin/Manager logins.
- **`settings`**: Key-value store for global configurations (e.g., `otp_enabled`, dynamic bank account lists).
- **`bank_accounts`**: Stores managed bank account details for payment receipt.
- **`audit_logs`**: Tracks cell-level edits. Indexed heavily by `document_id`, `field_name`, `collection_name`, and `edited_at` for rapid history rendering.

---

## 6. Authentication and Authorization (`app/auth.py`)

### 6.1. Role-Based Access Control (RBAC)
Users belong to one of three roles defined in an Enum:
1. `SUPER_ADMIN`: Full system access, can create other Admins.
2. `ADMIN` / `MANAGER`: High-level access, can create employees, requires OTP to login.
3. `EMPLOYEE`: Standard access, restricted ID ranges, standard login.

### 6.2. Login Flow
1. User submits Email and Password.
2. If role is Admin/Manager, the system checks `settings_collection` for `otp_enabled`.
3. If enabled, the system generates a 6-digit OTP, stores it in `otps_collection`, and emails it via `aiosmtplib`. The API returns `otp_required=True`.
4. User submits OTP to `/verify-otp`.
5. Upon success (or direct login for Employees), a JWT is generated via `pyjwt` and stored in `tokens_collection` for session tracking.

### 6.3. Dependency Injection
FastAPI's dependency injection is used extensively to protect routes.
- `get_current_user`: Extracts and validates the JWT, ensuring the token exists in the database.
- `require_admin`: Wraps `get_current_user` and enforces `UserRole.ADMIN`.
- `require_manager_or_higher`: Wraps `get_current_user` and enforces Admin or Manager roles.

---

## 7. Data Validation and Standardized Responses (`app/schemas.py`)

Pydantic models define the exact structure of data moving in and out of the system.

### 7.1. Unified API Wrapper
Every single API response is wrapped in a generic `ApiResponse[T]` Pydantic model. This guarantees the frontend receives a predictable shape:
```python
class ApiResponse(BaseModel, Generic[T]):
    status_code: int
    status: str
    message: str
    data: Optional[T] = None
```

### 7.2. Complex Schemas
The system uses modular schemas. For example, `OrderResponse` is built from `OrderBase`, and `DashboardOrderResponse` aggregates order details alongside lists of `PaymentResponse` objects, flattening complex MongoDB relationships into clean JSON.

---

## 8. Business Logic & Caching Modules

### 8.1. Currency Conversion (`app/currency_converter.py`)
Provides dynamic conversion between multiple currencies (USD, INR, AED, CNY, SAR). It likely interfaces with an external exchange rate API and implements internal mechanisms to handle floating point math safely.

### 8.2. Application Cache (`app/cache.py`)
To prevent heavy MongoDB aggregation queries from running on every page load (especially for the Dashboard), an in-memory dictionary cache (`cache_manager`) is implemented.
- The cache stores JSON representations of complex queries.
- Functions like `invalidate_dashboard_cache()` are called strategically inside POST/PUT/DELETE routes to purge stale data immediately when an underlying record changes.

### 8.3. Audit Logging
A helper function `record_audit_log` compares dictionaries (`old_doc` vs `new_doc`) during PUT requests. If a change is detected (excluding `_id` and `updated_at`), a granular log is pushed to the `audit_logs` collection detailing exactly who changed what, and when.

---

## 9. Data Flow Example: Updating an Order

1. **Client Action:** The user edits the "Received Bank Account" for an order on the frontend.
2. **Network Request:** A `PUT /dashboard/orders/{order_id}` request is fired with a Bearer Token.
3. **Middleware:** Custom middleware records the start time. CORS verifies the origin.
4. **Auth Dependency:** FastAPI runs `get_current_user`, decodes the JWT, verifies it exists in the DB, and attaches the user document to the request context.
5. **Validation:** Pydantic validates the incoming JSON against the `DashboardUpdate` schema.
6. **Route Logic (`app/api/routes.py`):**
   - The original order document is fetched.
   - The changes are applied to a `new_doc` dictionary.
   - `record_audit_log()` compares the documents and creates an entry in `audit_logs`.
   - `orders_collection.update_one()` persists the changes.
   - `invalidate_dashboard_cache()` is triggered to clear stale analytical data.
7. **Response:** An `ApiResponse` object is serialized and returned to the client.
8. **Performance:** Middleware logs the total time taken to process the request.
