from typing import Optional, Any, Annotated
from pydantic import Json
import re
import os
import random
from email.message import EmailMessage
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status, Form, File, UploadFile, Response, Query
from fastapi.responses import ORJSONResponse
from bson import ObjectId
from bson.binary import Binary

from app.schemas import (
    UserCreate,
    UserResponse,
    UserDetailResponse,
    LoginRequest,
    Token,
    UserRole,
    PasswordUpdate,
    AdminPasswordUpdate,
    ClientCreate,
    ClientResponse,
    ManuscriptCreate,
    ManuscriptResponse,
    OrderCreate,
    OrderResponse,
    PaymentCreate,
    PaymentResponse,
    DashboardOrderResponse,
    LoginResponse,
    OTPVerifyRequest,
    PermissionUpdate,
    ProfileUpdate,
    UserProfileUpdate,
    DashboardUpdate,
    ApiResponse,
    ClientAssignRequest,
    ClientBulkDeleteRequest,
    UnifiedCreateRequest,
    PaymentHistoryItem,
    PendingSummaryResponse,
    PendingClientDetail,
    ORDER_TYPE_OPTIONS,
    CurrencyConvertRequest,
    ClientFullResponse,
    ClientOrderSummary,
    BankAccountCreate,
    BankAccountUpdate,
    BankAccountResponse,
    SettingCategory,
    LookupSettingsData,
    SettingItemAction,
    SettingItemUpdateAction,
)
from app.config import SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_FROM, OTP_ENABLED
from app.auth import (
    encrypt_password,
    decrypt_password,
    verify_password,
    create_access_token,
    get_current_user,
    require_admin,
    require_manager_or_higher,
    oauth2_scheme,
)
from app.database import (
    users_collection,
    tokens_collection,
    clients_collection,
    manuscripts_collection,
    orders_collection,
    payments_collection,
    payment_history_collection,
    otps_collection,
    settings_collection,
    bank_accounts_collection,
    audit_logs_collection,
)
from app.currency_converter import convert_inr_to_usd, convert_usd_to_inr, get_current_rate_info, convert_currency
from app.cache import cache_manager, dashboard_cache_key, invalidate_dashboard_cache

router = APIRouter()
# --- HELPER ---
def record_audit_log(document_id: str, collection_name: str, old_doc: dict, new_doc: dict, user_email: str):
    """Compares old_doc and new_doc, and records changes to audit_logs_collection."""
    for key, new_val in new_doc.items():
        if key in ["_id", "updated_at"]: continue
        old_val = old_doc.get(key)
        if old_val != new_val:
            audit_logs_collection.insert_one({
                "document_id": str(document_id),
                "collection_name": collection_name,
                "field_name": key,
                "old_value": old_val,
                "new_value": new_val,
                "edited_by": user_email,
                "edited_at": datetime.utcnow()
            })

from datetime import datetime as _dt

_DATE_MIN = _dt.min
_DATE_MAX = _dt.max

def _to_date_key(value):
    """Normalise a date field value (str | datetime | None) to a datetime for sorting.
    Returns _DATE_MAX for None/unparseable values so they sort last.
    """
    if value is None:
        return _DATE_MAX
    if isinstance(value, _dt):
        return value
    # Try common ISO-like string formats
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return _dt.strptime(str(value)[:19], fmt)
        except ValueError:
            continue
    return _DATE_MAX

ALLOWED_DATE_SORT_FIELDS = {
    "order_date", "writing_start_date", "writing_end_date",
    "modification_start_date", "modification_end_date",
    "po_start_date", "po_end_date",
}

def _filter_and_paginate(data: list[dict], page: int = 1, limit: int = 25, sort_by: str = None, sort_order: str = None) -> tuple[list[dict], dict, dict]:
    """Simple pagination helper.
    Returns a slice of `data` for the requested page/limit, pagination metadata, and an empty filter options dict.
    Supports optional date-field sorting via sort_by / sort_order ('asc' | 'desc').
    """
    # --- Sorting (date fields only) ---
    if sort_by and sort_by in ALLOWED_DATE_SORT_FIELDS and sort_order in ("asc", "desc"):
        reverse = sort_order == "desc"
        data = sorted(
            data,
            key=lambda row: _to_date_key(row.get(sort_by)),
            reverse=reverse,
        )

    total_items = len(data)
    total_pages = (total_items + limit - 1) // limit if limit else 1
    if page > total_pages:
        page = max(total_pages, 1)
    start = (page - 1) * limit
    end = start + limit
    paginated = data[start:end]
    pagination_meta = {
        "page": page,
        "limit": limit,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_previous": page > 1,
    }
    # Placeholder for any future filter options; currently none.
    filter_opts: dict = {}
    return paginated, pagination_meta, filter_opts
def is_otp_enabled() -> bool:
    """
    Check if OTP authentication is enabled.
    Checks database settings first, then falls back to SMTP / config settings.
    """
    setting = settings_collection.find_one({"key": "otp_enabled"})
    if setting is not None:
        return bool(setting.get("value", True))
    return OTP_ENABLED

async def send_otp_email(to_email: str, otp: str):
    """
    Sends an OTP email via SMTP asynchronously.
    """
    msg = EmailMessage()
    msg.set_content(f"Your OTP for login is: {otp}\n\nThis OTP is valid for 5 minutes.")
    msg["Subject"] = "Login OTP - Email Dashboard"
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email

    # DEBUG: Print OTP for testing purposes
    print(f"\n[SECURE] [TEST OTP] For email {to_email}: {otp}")
    print("[WARNING] This OTP is printed for testing only!\n")

    print(f"\n[OTP DEBUG] Attempting to send email to {to_email} via {SMTP_SERVER}:{SMTP_PORT}\n")
    try:
        import aiosmtplib
    except ImportError as e:
        print(f"AIOSMTPLIB_MISSING: {e}")
        return False

    try:
        if SMTP_PORT == 465:
            # Port 465 requires SMTP_SSL from the start
            server = aiosmtplib.SMTP(hostname=SMTP_SERVER, port=SMTP_PORT, use_tls=True)
            await server.connect()
            await server.login(SMTP_USERNAME, SMTP_PASSWORD)
            await server.send_message(msg)
            await server.quit()
        else:
            # Port 587 (and others) typically use STARTTLS
            server = aiosmtplib.SMTP(hostname=SMTP_SERVER, port=SMTP_PORT)
            await server.connect()
            await server.start_tls()
            await server.login(SMTP_USERNAME, SMTP_PASSWORD)
            await server.send_message(msg)
            await server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def format_mongo_id(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc

import uuid

async def save_upload_file(upload_file, subfolder: str) -> str:
    """
    Save an UploadFile to static/uploads/{subfolder}/ and return the relative path.
    The returned path is what gets stored in MongoDB.
    """
    ext = os.path.splitext(upload_file.filename or "")[1]
    if not ext:
        # Derive extension from MIME type if filename has none
        mime = getattr(upload_file, "content_type", "") or ""
        ext = ".jpg" if "jpeg" in mime else ".png" if "png" in mime else ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    dir_path = os.path.join("static", "uploads", subfolder)
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, filename)
    content = await upload_file.read()
    with open(file_path, "wb") as f:
        f.write(content)
    return f"static/uploads/{subfolder}/{filename}"

def save_bytes_to_file(content: bytes, mime: str, subfolder: str) -> str:
    """
    Save raw bytes (e.g. decoded base64) to static/uploads/{subfolder}/ and return the relative path.
    """
    ext = ".jpg" if "jpeg" in mime else ".png" if "png" in mime else ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    dir_path = os.path.join("static", "uploads", subfolder)
    os.makedirs(dir_path, exist_ok=True)
    file_path = os.path.join(dir_path, filename)
    with open(file_path, "wb") as f:
        f.write(content)
    return f"static/uploads/{subfolder}/{filename}"

def delete_file_if_exists(path: Optional[str]):
    """Remove a file from the filesystem if it exists (called before replacing or deleting images)."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass

def parse_date(date_str: Any) -> Optional[datetime]:
    """Helper to convert string dates to datetime objects for MongoDB."""
    if not date_str:
        return None
    if isinstance(date_str, datetime):
        return date_str
    try:
        # Handle simple date strings like "2024-01-01"
        if len(date_str) == 10:
            return datetime.strptime(date_str, "%Y-%m-%d")
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except Exception:
        return None

def resolve_client_handler(client: dict) -> dict:
    """
    Resolves client_handler (email) to client_handler_name (full_name) for display.
    client_handler stores the employee's email for uniqueness.
    client_handler_name is the human-readable full name shown on the frontend.
    """
    handler_email = client.get("client_handler")
    if handler_email:
        handler_user = users_collection.find_one({"email": handler_email})
        client["client_handler_name"] = handler_user.get("full_name") if handler_user else handler_email
    else:
        client["client_handler_name"] = None
    return client

def resolve_client_handler_bulk(clients: list[dict]) -> list[dict]:
    """Resolve handler names for many clients with a single DB query."""
    emails = {client.get("client_handler") for client in clients if client.get("client_handler")}
    if not emails:
        for client in clients:
            client["client_handler_name"] = None
        return clients

    # Fetch only necessary fields (exclude whatsapp_numbers)
    handlers = users_collection.find({"email": {"$in": list(emails)}}, {"email": 1, "full_name": 1, "phone_number": 1})
    email_to_handler = {handler["email"]: handler for handler in handlers}
    for client in clients:
        handler_email = client.get("client_handler")
        if handler_email and handler_email in email_to_handler:
            client["client_handler_name"] = email_to_handler[handler_email].get("full_name", handler_email)
            client["client_handler_phone_number"] = email_to_handler[handler_email].get("phone_number")
        else:
            client["client_handler_name"] = None
            client["client_handler_phone_number"] = None
    return clients

def get_user_email_by_name(name_or_email: str) -> str:
    """
    Finds a user's email by their full name or returns the input if it's already an email.
    """
    if not name_or_email:
        return name_or_email
        
    # If it looks like an email, return as is
    if "@" in name_or_email:
        return name_or_email
        
    # Try to find user by full name
    user = users_collection.find_one({"full_name": name_or_email})
    if user:
        return user.get("email")
        
    return name_or_email


def generate_custom_id(prefix: str, collection, current_user: dict):
    """
    Generates a unique ID based on the user's assigned range.
    Format: {prefix}-{YYYY}-{num}
    """
    year = datetime.utcnow().strftime("%Y")
    
    # 1. Determine range
    if current_user["role"] == UserRole.ADMIN:
        start, end = 1, 9999
    else:
        # Default range if not set or if it is None
        start = current_user.get("id_range_start")
        start = start if start is not None else 100
        end = current_user.get("id_range_end")
        end = end if end is not None else 200
    
    # 2. Find existing IDs in this range for this year
    field_name = "client_id" if prefix == "CL" else "reference_id"
    pattern = f"^{prefix}-{year}-(\\d+)$"
    
    cursor = collection.find({
        field_name: {"$regex": pattern}
    })
    
    existing_nums = []
    for doc in cursor:
        val = doc.get(field_name)
        match = re.search(f"{prefix}-{year}-(\\d+)", val)
        if match:
            num = int(match.group(1))
            if start <= num <= end:
                existing_nums.append(num)
    
    # 3. Find next available number
    if not existing_nums:
        next_num = start
    else:
        next_num = max(existing_nums) + 1
        
    if next_num > end:
        raise HTTPException(
            status_code=400,
            detail=f"Limit reached for your assigned ID range ({start}-{end}). Please contact Admin."
        )
        
    return f"{prefix}-{year}-{next_num:04d}"

def is_id_range_overlapping(start: int, end: int, exclude_email: Optional[str] = None):
    """
    Checks if a given ID range overlaps with any existing user's range.
    """
    if start is None or end is None:
        return False
        
    query = {
        "role": UserRole.EMPLOYEE,
        "id_range_start": {"$exists": True},
        "id_range_end": {"$exists": True}
    }
    if exclude_email:
        query["email"] = {"$ne": exclude_email}
        
    existing_users = users_collection.find(query)
    
    for user in existing_users:
        e_start = user.get("id_range_start")
        e_end = user.get("id_range_end")
        
        if e_start is None or e_end is None:
            continue
            
        # Check for overlap: (StartA <= EndB) and (EndA >= StartB)
        if (start <= e_end) and (end >= e_start):
            return user.get("email")
            
    return None



@router.get("/", response_model=ApiResponse[dict])
def read_root():
    return {
        "status_code": 200,
        "status": "success",
        "message": "Welcome to Email Dashboard API",
        "data": None
    }

# --- CURRENCY CONVERSION ---

@router.get("/currency/exchange-rate", response_model=ApiResponse[dict])
def get_exchange_rate():
    """
    Get current INR to USD exchange rate with caching.
    """
    rate_info = get_current_rate_info()
    if not rate_info:
        raise HTTPException(
            status_code=503,
            detail="Exchange rate service unavailable"
        )
    return {
        "status_code": 200,
        "status": "success",
        "message": "Exchange rate fetched successfully",
        "data": rate_info
    }

@router.post("/currency/inr-to-usd", response_model=ApiResponse[dict])
def convert_inr_to_usd_endpoint(amount: dict):
    """
    Convert amount from INR to USD.
    Request: {"amount_inr": 1000}
    Response includes current rate and converted amount.
    """
    amount_inr = amount.get("amount_inr")
    if amount_inr is None or amount_inr < 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid amount_inr. Must be a positive number."
        )
    
    result = convert_inr_to_usd(float(amount_inr))
    if not result:
        raise HTTPException(
            status_code=503,
            detail="Exchange rate service unavailable"
        )
    
    return {
        "status_code": 200,
        "status": "success",
        "message": "Conversion completed successfully",
        "data": result
    }

@router.post("/currency/usd-to-inr", response_model=ApiResponse[dict])
def convert_usd_to_inr_endpoint(amount: dict):
    """
    Convert amount from USD to INR.
    Request: {"amount_usd": 15}
    Response includes current rate and converted amount.
    """
    amount_usd = amount.get("amount_usd")
    if amount_usd is None or amount_usd < 0:
        raise HTTPException(
            status_code=400,
            detail="Invalid amount_usd. Must be a positive number."
        )
    
    result = convert_usd_to_inr(float(amount_usd))
    if not result:
        raise HTTPException(
            status_code=503,
            detail="Exchange rate service unavailable"
        )
    
    return {
        "status_code": 200,
        "status": "success",
        "message": "Conversion completed successfully",
        "data": result
    }

@router.post("/currency/convert", response_model=ApiResponse[dict])
def convert_currency_endpoint(request: CurrencyConvertRequest):
    """
    Convert amount between any supported currencies (USD, INR, CNY, AED, SAR).
    """
    result = convert_currency(request.amount, request.from_currency, request.to_currency)
    if not result:
        raise HTTPException(
            status_code=400,
            detail="Currency conversion failed. Verify the input parameters."
        )
    return {
        "status_code": 200,
        "status": "success",
        "message": "Conversion completed successfully",
        "data": result
    }

# --- INITIALIZATION ---

@router.post("/init-super-admin", response_model=ApiResponse[dict], status_code=status.HTTP_201_CREATED)
def init_super_admin(user: UserCreate):
    """
    Endpoint to initialize the first super admin users. 
    Works if fewer than 5 admins exist in the database.
    """
    admin_count = users_collection.count_documents({"role": UserRole.ADMIN})
    if admin_count >= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Maximum of 5 Admins already exist"
        )
    
    user_dict = user.model_dump()
    user_dict["password"] = encrypt_password(user.password)
    user_dict["role"] = UserRole.ADMIN
    users_collection.insert_one(user_dict)
    
    return {
        "status_code": 201,
        "status": "success",
        "message": "Super Admin created successfully",
        "data": None
    }

# --- LOGIN ---

@router.post("/login", response_model=ApiResponse[LoginResponse])
async def login(request: LoginRequest):
    """
    Shared login endpoint. Admins and Managers require OTP.
    Employees login directly.
    """
    user = users_collection.find_one({"email": request.email})
    if not user or not verify_password(request.password, user["password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if role requires OTP (Admin and Manager)
    if is_otp_enabled() and user["role"] in [UserRole.ADMIN, UserRole.MANAGER]:
        otp = str(random.randint(100000, 999999))
        
        # Store OTP
        otps_collection.update_one(
            {"email": user["email"]},
            {"$set": {
                "otp": otp,
                "created_at": datetime.utcnow()
            }},
            upsert=True
        )
        
        # Send OTP asynchronously
        sent = await send_otp_email(user["email"], otp)
        
        return {
            "status_code": 200,
            "status": "success",
            "message": "OTP required move to verify-otp",
            "data": LoginResponse(otp_required=True, email=user["email"])
        }

    # Regular login for Employee
    access_token = create_access_token(data={"sub": user["email"]})
    
    # Store token
    tokens_collection.insert_one({
        "user_email": user["email"],
        "token": access_token,
        "created_at": datetime.utcnow()
    })
    
    return {
        "status_code": 200,
        "status": "success",
        "message": "Login successful",
        "data": LoginResponse(access_token=access_token, token_type="bearer")
    }

@router.post("/verify-otp", response_model=ApiResponse[Token])
def verify_otp(request: OTPVerifyRequest):
    """
    Verify OTP for Admin/Manager login.
    """
    # Check OTP record
    otp_record = otps_collection.find_one({"email": request.email})
    
    if not otp_record or otp_record["otp"] != request.otp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired OTP"
        )
    
    # OTP is valid, check expiration (e.g., 5 minutes)
    if datetime.utcnow() - otp_record["created_at"] > timedelta(minutes=5):
        otps_collection.delete_one({"email": request.email})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OTP has expired"
        )
    
    # OTP verified, issue token
    user = users_collection.find_one({"email": request.email})
    access_token = create_access_token(data={"sub": user["email"]})
    
    # Store token
    tokens_collection.insert_one({
        "user_email": user["email"],
        "token": access_token,
        "created_at": datetime.utcnow()
    })
    
    # Clear OTP
    otps_collection.delete_one({"email": request.email})
    
    return {
        "status_code": 200,
        "status": "success",
        "message": "OTP verified successfully",
        "data": {"access_token": access_token, "token_type": "bearer"}
    }

@router.post("/logout", response_model=ApiResponse[dict])
async def logout(token: str = Depends(oauth2_scheme), current_user: dict = Depends(get_current_user)):
    """
    Logout the current user by invalidating their token.
    """
    tokens_collection.delete_one({"token": token})
    return {
        "status_code": 200,
        "status": "success",
        "message": "Logged out successfully",
        "data": None
    }

@router.get("/otp-status", response_model=ApiResponse[dict])
def get_otp_status():
    """
    Get the current status of OTP verification (enabled/disabled).
    """
    enabled = is_otp_enabled()
    return {
        "status_code": 200,
        "status": "success",
        "message": f"OTP verification is {'enabled' if enabled else 'disabled'}",
        "data": {"otp_enabled": enabled}
    }

@router.post("/toggle-otp", response_model=ApiResponse[dict])
def toggle_otp(enabled: bool):
    """
    Enable or disable OTP verification globally.
    """
    settings_collection.update_one(
        {"key": "otp_enabled"},
        {"$set": {"value": enabled}},
        upsert=True
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"OTP verification has been {'enabled' if enabled else 'disabled'}",
        "data": {"otp_enabled": enabled}
    }

# --- USER & ADMIN CREATION ---

@router.post("/users", response_model=ApiResponse[UserResponse], status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate, current_user: dict = Depends(require_manager_or_higher)):
    """
    Create a new User (Admin, Manager, or Employee).
    Restricted to Super Admin and Manager. 
    One additional Admin is allowed (total 2).
    """
    # Check if user already exists
    if users_collection.find_one({"email": user.email}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Email already registered"
        )
    
    # Check for ID range overlap
    if user.id_range_start is not None and user.id_range_end is not None:
        overlapping_user = is_id_range_overlapping(user.id_range_start, user.id_range_end)
        if overlapping_user:
            raise HTTPException(
                status_code=400, 
                detail=f"ID range {user.id_range_start}-{user.id_range_end} overlaps with user: {overlapping_user}"
            )
    
    # Logic for Admin role restriction
    if user.role == UserRole.ADMIN:
        # Only existing Admin can create another Admin
        if current_user["role"] != UserRole.ADMIN:
             raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only Super Admin can create another Admin"
            )
             
        admin_count = users_collection.count_documents({"role": UserRole.ADMIN})
        if admin_count >= 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum of 5 Admins allowed"
            )
            
    user_dict = user.model_dump()
    user_dict["password"] = encrypt_password(user.password)
    result = users_collection.insert_one(user_dict)
    
    user_dict["_id"] = str(result.inserted_id)
    user_dict["password"] = user.password
    return {
        "status_code": 201,
        "status": "success",
        "message": "User created successfully",
        "data": user_dict
    }

@router.post("/managers", response_model=ApiResponse[UserResponse], status_code=status.HTTP_201_CREATED)
def create_manager(user: UserCreate, current_user: dict = Depends(require_manager_or_higher)):
    """
    Create a new Manager.
    Restricted to Admin and Manager only.
    """
    # Check if user already exists
    if users_collection.find_one({"email": user.email}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Email already registered"
        )
    
    # Enforce role to be Manager
    user_dict = user.model_dump()
    user_dict["role"] = UserRole.MANAGER
    user_dict["password"] = encrypt_password(user.password)
    result = users_collection.insert_one(user_dict)
    
    user_dict["_id"] = str(result.inserted_id)
    user_dict["password"] = user.password
    return {
        "status_code": 201,
        "status": "success",
        "message": "Manager created successfully",
        "data": user_dict
    }

# --- PASSWORD MANAGEMENT ---

@router.put("/users/me/password", response_model=ApiResponse[dict])
def update_own_password(data: PasswordUpdate, current_user: dict = Depends(get_current_user)):
    """
    Update own password. Available to all roles.
    """
    hashed_password = encrypt_password(data.new_password)
    users_collection.update_one(
        {"email": current_user["email"]},
        {"$set": {"password": hashed_password}}
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": "Password updated successfully",
        "data": None
    }

@router.put("/users/password", response_model=ApiResponse[dict])
def update_user_password(data: AdminPasswordUpdate, current_user: dict = Depends(require_manager_or_higher)):
    """
    Update a User's password. Restricted to Admin and Super Admin.
    Admins can only change USER role passwords.
    Super Admins can change ADMIN and USER role passwords.
    """
    target_user = users_collection.find_one({"email": data.email})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Admin can only change EMPLOYEE passwords
    if current_user["role"] == UserRole.MANAGER:
        if target_user["role"] != UserRole.EMPLOYEE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Managers can only change Employee passwords"
            )
    
    # Super Admin can change Admin or Manager passwords
    if current_user["role"] == UserRole.ADMIN:
         if target_user["role"] == UserRole.ADMIN and target_user["email"] != current_user["email"]:
              raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot change other Admin passwords"
            )

    hashed_password = encrypt_password(data.new_password)
    users_collection.update_one(
        {"email": data.email},
        {"$set": {"password": hashed_password}}
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Password for {data.email} updated successfully",
        "data": None
    }

# --- VISIBILITY ---

@router.get("/users", response_model=ApiResponse[list[UserResponse]])
def get_all_users(current_user: dict = Depends(require_manager_or_higher)):
    """
    Get all regular Users. Accessible to Admin and Super Admin.
    """
    import base64

    users = list(users_collection.find({"role": UserRole.EMPLOYEE}))
    for u in users:
        u["_id"] = str(u["_id"])
        # Decrypt password for display
        u["password"] = decrypt_password(u.get("password", ""))
        # Remove raw binary if any legacy data exists; serve URL instead
        u.pop("photo_data", None)
        u["photo_url"] = u.get("photo_path") or None
    return {
        "status_code": 200,
        "status": "success",
        "message": "Users fetched successfully",
        "data": users
    }

@router.get("/admins", response_model=ApiResponse[list[UserResponse]])
def get_all_admins(current_user: dict = Depends(require_admin)):
    """
    Get all Admins and Super Admins. Accessible to Super Admin only.
    """
    import base64

    admins = list(users_collection.find({"role": {"$in": [UserRole.MANAGER, UserRole.ADMIN]}}))
    for a in admins:
        a["_id"] = str(a["_id"])
        # Decrypt password for display
        a["password"] = decrypt_password(a.get("password", ""))
        # Remove raw binary if any legacy data exists; serve URL instead
        a.pop("photo_data", None)
        a["photo_url"] = a.get("photo_path") or None
    return {
        "status_code": 200,
        "status": "success",
        "message": "Admins fetched successfully",
        "data": admins
    }

@router.put("/users/permissions", response_model=ApiResponse[dict])
def update_user_permissions(data: PermissionUpdate, current_user: dict = Depends(require_manager_or_higher)):
    """
    Update an Employee's column-level permissions. 
    Restricted to Admin and Manager.
    """
    target_user = users_collection.find_one({"email": data.email})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Check if target is indeed an employee
    if target_user["role"] != UserRole.EMPLOYEE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Permissions can only be set for Employees"
        )

    # Check for ID range overlap
    if data.id_range_start is not None and data.id_range_end is not None:
        overlapping_user = is_id_range_overlapping(data.id_range_start, data.id_range_end, exclude_email=data.email)
        if overlapping_user:
            raise HTTPException(
                status_code=400, 
                detail=f"ID range {data.id_range_start}-{data.id_range_end} overlaps with user: {overlapping_user}"
            )

    users_collection.update_one(
        {"email": data.email},
        {"$set": {
            "id_range_start": data.id_range_start,
            "id_range_end": data.id_range_end
        }}
    )

    return {
        "status_code": 200,
        "status": "success",
        "message": f"ID range updated for {data.email}",
        "data": None
    }


@router.put("/users/profile", response_model=ApiResponse[UserResponse])
@router.put("/users/{email}/profile", response_model=ApiResponse[UserResponse])
async def update_user_profile(
    full_name: Optional[str] = Form(None),
    phone_number: Optional[str] = Form(None),
    personal_email: Optional[str] = Form(None),
    personal_number: Optional[str] = Form(None),
    branch: Optional[str] = Form(None),
    photo: Optional[UploadFile] = File(None),
    email: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    target_email = email or current_user["email"]
    
    # Check permissions
    if current_user["role"] != UserRole.ADMIN and current_user["email"] != target_email:
        raise HTTPException(status_code=403, detail="Not authorized to update this profile")
        
    update_dict = {}
    if full_name is not None: update_dict["full_name"] = full_name
    if phone_number is not None: update_dict["phone_number"] = phone_number
    if personal_email is not None: update_dict["personal_email"] = personal_email
    if personal_number is not None: update_dict["personal_number"] = personal_number
    if branch is not None: update_dict["branch"] = branch
    
    # Handle optional photo upload
    if photo is not None:
        if not photo.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="File must be an image")
        content = await photo.read()
        # Delete old photo file if it exists
        old_user = users_collection.find_one({"email": target_email})
        if old_user:
            delete_file_if_exists(old_user.get("photo_path"))
        # Save new photo to filesystem
        await photo.seek(0)
        photo_path = await save_upload_file(photo, "users")
        update_dict["photo_path"] = photo_path
        update_dict["photo_mime"] = photo.content_type
        update_dict["has_photo"] = True
        
    if not update_dict:
        raise HTTPException(status_code=400, detail="No fields to update")
        
    users_collection.update_one({"email": target_email}, {"$set": update_dict})
    updated_user = users_collection.find_one({"email": target_email})
    if not updated_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # Remove legacy binary data from response
    updated_user.pop("photo_data", None)
    # Inject photo_url for response
    updated_user["photo_url"] = updated_user.get("photo_path") or None
        
    # Decrypt password for schema consistency
    if "password" in updated_user:
        try:
            updated_user["password"] = decrypt_password(updated_user.get("password", ""))
        except Exception:
            pass
        
    return {
        "status_code": 200,
        "status": "success",
        "message": "Profile updated successfully",
        "data": format_mongo_id(updated_user)
    }

@router.get("/users/{email}/photo")
def get_user_photo(email: str):
    user = users_collection.find_one({"email": email})
    if user:
        photo_path = user.get("photo_path")
        if photo_path and os.path.exists(photo_path):
            from fastapi.responses import FileResponse
            return FileResponse(photo_path, media_type=user.get("photo_mime", "image/png"))
        
    # Fallback to static default avatar
    default_path = "static/default_user.png"
    if os.path.exists(default_path):
        from fastapi.responses import FileResponse
        return FileResponse(default_path, media_type="image/png")
    return Response(content=b"", status_code=404)

@router.post("/users/{email}/photo", status_code=200)
async def upload_user_photo(
    email: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload or update a user's profile photo.
    The authenticated user can update their own photo.
    Admin and Manager can update any user's photo.
    Saves file to static/uploads/users/ and stores the path in MongoDB.
    """
    # Allow self-update OR manager/admin updating any user
    if current_user["email"] != email and current_user.get("role") not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise HTTPException(status_code=403, detail="Not authorised to update this user's photo")
    
    target = users_collection.find_one({"email": email})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    content = await file.read()

    # Delete old photo file if it exists
    delete_file_if_exists(target.get("photo_path"))

    # Save to filesystem
    await file.seek(0)
    photo_path = await save_upload_file(file, "users")

    users_collection.update_one(
        {"email": email},
        {"$set": {
            "photo_path": photo_path,
            "photo_mime": file.content_type,
            "has_photo": True
        }}
    )
    return {"status": "success", "message": f"Photo updated for {email}", "photo_url": photo_path}

@router.delete("/users/{email}/photo", status_code=200)
def delete_user_photo(email: str, current_user: dict = Depends(get_current_user)):
    """Delete a user's profile photo."""
    if current_user["email"] != email and current_user.get("role") not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise HTTPException(status_code=403, detail="Not authorised to delete this user's photo")
        
    target = users_collection.find_one({"email": email})
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
        
    delete_file_if_exists(target.get("photo_path"))
    
    users_collection.update_one(
        {"email": email},
        {"$set": {
            "photo_path": None,
            "photo_mime": None,
            "has_photo": False
        }}
    )
    return {"status": "success", "message": f"Photo deleted for {email}"}

@router.post("/clients/{client_id}/photo", status_code=200)
async def upload_client_photo(
    client_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    content = await file.read()

    # Delete old photo file
    existing = clients_collection.find_one({"client_id": client_id})
    if existing:
        delete_file_if_exists(existing.get("photo_path"))

    # Save to filesystem
    await file.seek(0)
    photo_path = await save_upload_file(file, "clients")

    clients_collection.update_one(
        {"client_id": client_id},
        {"$set": {
            "photo_path": photo_path,
            "photo_mime": file.content_type,
            "has_photo": True
        }}
    )
    return {"status": "success", "message": "Client photo uploaded successfully", "photo_url": photo_path}

@router.delete("/clients/{client_id}/photo", status_code=200)
def delete_client_photo(client_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a client's profile photo."""
    target = clients_collection.find_one({"client_id": client_id})
    if not target:
        raise HTTPException(status_code=404, detail="Client not found")
        
    delete_file_if_exists(target.get("photo_path"))
    
    clients_collection.update_one(
        {"client_id": client_id},
        {"$set": {
            "photo_path": None,
            "photo_mime": None,
            "has_photo": False
        }}
    )
    return {"status": "success", "message": f"Client photo deleted successfully"}

@router.get("/clients/{client_id}/photo")
def get_client_photo(client_id: str):
    client_doc = clients_collection.find_one({"client_id": client_id})
    if client_doc:
        photo_path = client_doc.get("photo_path")
        if photo_path and os.path.exists(photo_path):
            from fastapi.responses import FileResponse
            return FileResponse(photo_path, media_type=client_doc.get("photo_mime", "image/png"))
        
    # Fallback to static default client avatar
    default_path = "static/default_client.png"
    if os.path.exists(default_path):
        from fastapi.responses import FileResponse
        return FileResponse(default_path, media_type="image/png")
    return Response(content=b"", status_code=404)

# --- RECEIPT SCREENSHOT ENDPOINTS ---

@router.post("/orders/{order_db_id}/receipt/{phase}", status_code=200)
async def upload_receipt_screenshot(
    order_db_id: str,
    phase: int,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Upload a payment receipt screenshot/document for an order phase (1, 2, or 3).
    - Accepts images (png, jpg, etc.), PDFs, and Word docs
    - Enforces 10 MB size limit
    - Saves file to static/uploads/receipts/ and stores path in orders collection
    - Clears dashboard cache after successful upload
    """
    from app.cache import clear_dashboard_cache
    
    # Validate phase
    if phase not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Phase must be 1, 2, or 3")
    
    # Validate file type — allow images, PDFs, and Word documents
    allowed_types = (
        "image/",
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    if not any(file.content_type.startswith(t) for t in allowed_types):
        raise HTTPException(status_code=400, detail="File must be an image, PDF, or Word document")
    
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="File size must be less than 10MB")
    
    # Verify order exists
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_db_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_db_id format")
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Delete old receipt file if it exists
    old_path = order.get(f"receipt_phase_{phase}_path")
    delete_file_if_exists(old_path)

    # Save to filesystem
    await file.seek(0)
    receipt_path = await save_upload_file(file, "receipts")

    # Store receipt path in DB
    updates = {
        f"receipt_phase_{phase}_path": receipt_path,
        f"receipt_phase_{phase}_mime": file.content_type
    }
    orders_collection.update_one(
        {"_id": ObjectId(order_db_id)},
        {"$set": updates}
    )
    
    # Log with the exact field name the frontend requests
    log_updates = {f"phase_{phase}_receipt": receipt_path}
    log_old = {f"phase_{phase}_receipt": order.get(f"receipt_phase_{phase}_path")}
    record_audit_log(str(order_db_id), "orders", log_old, log_updates, current_user.get("email", "unknown"))
    
    # Clear cache
    clear_dashboard_cache()
    
    return {
        "status": "success",
        "message": f"Receipt screenshot for phase {phase} uploaded successfully",
        "receipt_url": receipt_path
    }

@router.get("/orders/{order_db_id}/receipt/{phase}")
def get_receipt_screenshot(order_db_id: str, phase: int):
    """
    Download/serve a payment receipt screenshot for an order phase.
    Returns the image file from disk, or 404 if not found.
    """
    from fastapi.responses import FileResponse
    # Validate phase
    if phase not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Phase must be 1, 2, or 3")
    
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_db_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_db_id format")
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    receipt_path = order.get(f"receipt_phase_{phase}_path")
    if not receipt_path or not os.path.exists(receipt_path):
        raise HTTPException(status_code=404, detail=f"No receipt found for phase {phase}")
    
    receipt_mime = order.get(f"receipt_phase_{phase}_mime", "image/png")
    return FileResponse(receipt_path, media_type=receipt_mime)

@router.delete("/orders/{order_db_id}/receipt/{phase}", status_code=200)
def delete_receipt_screenshot(
    order_db_id: str,
    phase: int,
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a payment receipt screenshot from an order phase.
    Removes the file from disk and unsets the path field in MongoDB.
    """
    from app.cache import clear_dashboard_cache
    
    # Validate phase
    if phase not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Phase must be 1, 2, or 3")
    
    # Verify order exists
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_db_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid order_db_id format")
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Delete file from filesystem
    old_path = order.get(f"receipt_phase_{phase}_path")
    delete_file_if_exists(old_path)

    # Remove path from DB
    orders_collection.update_one(
        {"_id": ObjectId(order_db_id)},
        {"$unset": {
            f"receipt_phase_{phase}_path": "",
            f"receipt_phase_{phase}_mime": ""
        }}
    )
    
    # Log with the exact field name the frontend requests
    log_updates = {f"phase_{phase}_receipt": None}
    log_old = {f"phase_{phase}_receipt": order.get(f"receipt_phase_{phase}_path")}
    record_audit_log(str(order_db_id), "orders", log_old, log_updates, current_user.get("email", "unknown"))
    
    # Clear cache
    clear_dashboard_cache()
    
    return {
        "status": "success",
        "message": f"Receipt screenshot for phase {phase} deleted successfully"
    }



@router.post("/users/profiles/append", response_model=ApiResponse[dict])
def append_profile_name(data: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    """Append a new profile name to a user's list."""
    target_user = users_collection.find_one({"email": data.email})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    users_collection.update_one(
        {"email": data.email},
        {"$addToSet": {"profile_names": data.profile_name}}
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Profile '{data.profile_name}' added to {data.email}",
        "data": None
    }

@router.post("/users/we_chats/append", response_model=ApiResponse[dict])
def append_we_chat(data: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    """Append a new WeChat account to a user's list."""
    target_user = users_collection.find_one({"email": data.email})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    users_collection.update_one(
        {"email": data.email},
        {"$addToSet": {"we_chats": data.profile_name}}
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"WeChat '{data.profile_name}' added to {data.email}",
        "data": None
    }

@router.post("/users/whatsapp_numbers/append", response_model=ApiResponse[dict])
def append_whatsapp_number(data: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    """Append a new WhatsApp number to a user's list."""
    target_user = users_collection.find_one({"email": data.email})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    users_collection.update_one(
        {"email": data.email},
        {"$addToSet": {"whatsapp_numbers": data.profile_name}}
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"WhatsApp number '{data.profile_name}' added to {data.email}",
        "data": None
    }

@router.delete("/users/whatsapp_numbers/{email}/{whatsapp_number}", response_model=ApiResponse[dict])
def delete_whatsapp_number(email: str, whatsapp_number: str, current_user: dict = Depends(get_current_user)):
    """Remove a WhatsApp number from a user's list."""
    if current_user["email"] != email and current_user.get("role") not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise HTTPException(status_code=403, detail="Not authorized to update this user's profile")
        
    users_collection.update_one(
        {"email": email},
        {"$pull": {"whatsapp_numbers": whatsapp_number}}
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"WhatsApp number '{whatsapp_number}' removed from {email}",
        "data": None
    }

@router.delete("/users/we_chats/{email}/{we_chat}", response_model=ApiResponse[dict])
def delete_we_chat(email: str, we_chat: str, current_user: dict = Depends(get_current_user)):
    """Remove a WeChat account from a user's list."""
    if current_user["email"] != email and current_user.get("role") not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise HTTPException(status_code=403, detail="Not authorized to update this user's profile")
        
    users_collection.update_one(
        {"email": email},
        {"$pull": {"we_chats": we_chat}}
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"WeChat '{we_chat}' removed from {email}",
        "data": None
    }


@router.delete("/users/profiles/{email}/{profile_name}", response_model=ApiResponse[dict])
def delete_profile_name(email: str, profile_name: str, current_user: dict = Depends(get_current_user)):
    """Remove a profile name from a user's list."""
    if current_user["email"] != email and current_user.get("role") not in [UserRole.ADMIN, UserRole.MANAGER]:
        raise HTTPException(status_code=403, detail="Not authorized to update this user's profile")
        
    users_collection.update_one(
        {"email": email},
        {"$pull": {"profile_names": profile_name}}
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Profile '{profile_name}' removed from {email}",
        "data": None
    }

# @router.put("/users/profiles/update", response_model=ApiResponse[dict])
# def update_profile_name(data: ProfileUpdate, current_user: dict = Depends(require_manager_or_higher)):
#     """Update an existing profile name in a user's list."""
#     if not data.new_profile_name:
#         raise HTTPException(status_code=400, detail="new_profile_name is required for update")
        
#     target_user = users_collection.find_one({"email": data.email})
#     if not target_user:
#         raise HTTPException(status_code=404, detail="User not found")
        
#     # Atomic update of specific element in array
#     result = users_collection.update_one(
#         {"email": data.email, "profile_names": data.profile_name},
#         {"$set": {"profile_names.$": data.new_profile_name}}
#     )
    
#     if result.matched_count == 0:
#         raise HTTPException(status_code=404, detail=f"Profile '{data.profile_name}' not found for this user")

#     return {
#         "status_code": 200,
#         "status": "success",
#         "message": f"Profile '{data.profile_name}' updated to '{data.new_profile_name}'",
#         "data": None
#     }

# @router.delete("/users/profiles/remove", response_model=ApiResponse[dict])
# def remove_profile_name(data: ProfileUpdate, current_user: dict = Depends(require_manager_or_higher)):
#     """Remove a profile name from a user's list."""
#     target_user = users_collection.find_one({"email": data.email})
#     if not target_user:
#         raise HTTPException(status_code=404, detail="User not found")
    
#     users_collection.update_one(
#         {"email": data.email},
#         {"$pull": {"profile_names": data.profile_name}}
#     )
#     return {
#         "status_code": 200,
#         "status": "success",
#         "message": f"Profile '{data.profile_name}' removed from {data.email}",
#         "data": None
#     }


def get_user_dashboard_data(client_match: dict):
    """
    Common logic to fetch dashboard stats, country stats, and order status details
    based on a client filter (e.g., all clients for Admin, or specific handler for Employee).
    """
    from app.currency_converter import get_all_inr_rates
    rates = get_all_inr_rates()
    usd_rate = rates.get("USD", 0.012)
    cny_rate = rates.get("CNY", 0.087)
    aed_rate = rates.get("AED", 0.044)
    sar_rate = rates.get("SAR", 0.045)
    
    multipliers = {
        "USD": 1.0,
        "INR": usd_rate,
        "CNY": usd_rate / cny_rate if cny_rate else 0.14,
        "AED": usd_rate / aed_rate if aed_rate else 0.272,
        "SAR": usd_rate / sar_rate if sar_rate else 0.267,
    }

    # 2. Aggregation Pipeline to fetch clients and their stats in ONE go
    pipeline = [
        {"$match": client_match},
        {
            "$lookup": {
                "from": "orders",
                "let": {"cid": "$client_id"},
                "pipeline": [
                    {"$match": {"$expr": {"$eq": ["$client_id", "$$cid"]}}},
                    {
                        "$lookup": {
                            "from": "payments",
                            "localField": "order_id",
                            "foreignField": "order_id",
                            "as": "order_payments"
                        }
                    },
                    {
                        "$addFields": {
                            "order_total_usd": {
                                "$switch": {
                                    "branches": [
                                        {"case": {"$eq": [{"$toUpper": "$currency"}, "INR"]}, "then": {"$multiply": ["$total_amount", multipliers["INR"]]}},
                                        {"case": {"$eq": [{"$toUpper": "$currency"}, "CNY"]}, "then": {"$multiply": ["$total_amount", multipliers["CNY"]]}},
                                        {"case": {"$eq": [{"$toUpper": "$currency"}, "AED"]}, "then": {"$multiply": ["$total_amount", multipliers["AED"]]}},
                                        {"case": {"$eq": [{"$toUpper": "$currency"}, "SAR"]}, "then": {"$multiply": ["$total_amount", multipliers["SAR"]]}}
                                    ],
                                    "default": "$total_amount"
                                }
                            },
                            "order_paid": {
                                "$sum": {
                                    "$map": {
                                        "input": "$order_payments",
                                        "as": "p",
                                        "in": {
                                            "$switch": {
                                                "branches": [
                                                    {"case": {"$eq": [{"$toUpper": "$currency"}, "INR"]}, "then": {"$multiply": [{"$ifNull": ["$$p.paid_amount", 0.0]}, multipliers["INR"]]}},
                                                    {"case": {"$eq": [{"$toUpper": "$currency"}, "CNY"]}, "then": {"$multiply": [{"$ifNull": ["$$p.paid_amount", 0.0]}, multipliers["CNY"]]}},
                                                    {"case": {"$eq": [{"$toUpper": "$currency"}, "AED"]}, "then": {"$multiply": [{"$ifNull": ["$$p.paid_amount", 0.0]}, multipliers["AED"]]}},
                                                    {"case": {"$eq": [{"$toUpper": "$currency"}, "SAR"]}, "then": {"$multiply": [{"$ifNull": ["$$p.paid_amount", 0.0]}, multipliers["SAR"]]}}
                                                ],
                                                "default": {"$ifNull": ["$$p.paid_amount", 0.0]}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "total_amount": {"$sum": "$order_total_usd"},
                            "paid_amount": {"$sum": "$order_paid"},
                            "order_count": {"$sum": 1},
                            "payment_status": {"$first": "$payment_status"},
                            "paid_order_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$payment_status", "Paid"]},
                                        1, 0
                                    ]
                                }
                            },
                            "pending_order_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$ne": ["$payment_status", "Paid"]},
                                                {"$ne": ["$order_status", "Inactive"]}
                                            ]
                                        },
                                        1, 0
                                    ]
                                }
                            },
                            "reject_order_count": {
                                "$sum": {"$cond": [{"$eq": ["$order_status", "Inactive"]}, 1, 0]}
                            },
                            "orders_list": {
                                "$push": {
                                    "client_id": "$client_id",
                                    "reference_id": "$reference_id",
                                    "order_status": "$order_status",
                                    "total_amount": "$order_total_usd",
                                    "paid_amount": "$order_paid",
                                    "is_new_order": "$is_new_order",
                                    "payment_status": "$payment_status",
                                    "created_at": "$created_at",
                                    "order_date": "$order_date"
                                }
                            }
                        }
                    }
                ],
                "as": "stats"
            }
        },
        {"$unwind": {"path": "$stats", "preserveNullAndEmptyArrays": True}},
        {
            "$addFields": {
                "total_amount": {"$ifNull": ["$stats.total_amount", 0.0]},
                "paid_amount": {"$ifNull": ["$stats.paid_amount", 0.0]},
                "order_count": {"$ifNull": ["$stats.order_count", 0]},
                "paid_order_count": {"$ifNull": ["$stats.paid_order_count", 0]},
                "pending_order_count": {"$ifNull": ["$stats.pending_order_count", 0]},
                "reject_order_count": {"$ifNull": ["$stats.reject_order_count", 0]},
                "orders_list": {"$ifNull": ["$stats.orders_list", []]}
            }
        },
        {"$project": {"stats": 0}}
    ]
    
    clients_with_stats = list(clients_collection.aggregate(pipeline))
    
    from collections import defaultdict
    country_stats_map = defaultdict(lambda: {
        "country_name": "",
        "client_count": 0,
        "order_count": 0,
        "paid_count": 0,
        "paid_amount": 0.0,
        "pending_count": 0,
        "reject_count": 0
    })
    order_status_details = []
    
    total_system_amount = 0.0
    total_system_paid = 0.0
    total_system_orders = 0
    total_system_pending = 0
    total_system_rejects = 0
    
    for c in clients_with_stats:
        country = c.get("country") or "Unknown"
        stats = country_stats_map[country]
        stats["country_name"] = country
        stats["client_count"] += 1
        
        c_order_count = c.get("order_count", 0)
        c_paid_order_count = c.get("paid_order_count", 0)
        c_paid_amount = c.get("paid_amount", 0.0)
        c_pending_order_count = c.get("pending_order_count", 0)
        c_reject_order_count = c.get("reject_order_count", 0)
        c_total_amount = c.get("total_amount", 0.0)
        
        stats["order_count"] += c_order_count
        stats["paid_count"] += c_paid_order_count
        stats["paid_amount"] = round(stats["paid_amount"] + c_paid_amount, 2)
        stats["pending_count"] += c_pending_order_count
        stats["reject_count"] += c_reject_order_count
        
        c_name = c.get("name")
        c_country = c.get("country")
        
        # Batch append to avoid constant resizing if possible
        order_status_details.extend({
            "client_name": c_name,
            "client_id": order.get("client_id"),
            "reference_id": order.get("reference_id"),
            "order_status": order.get("order_status"),
            "payment_status": order.get("payment_status"),
            "country": c_country,
            "total_amount": round(order.get("total_amount", 0.0), 2),
            "paid_amount": round(order.get("paid_amount", 0.0), 2),
            "is_new_order": order.get("is_new_order", "yes"),
            "created_at": order.get("created_at"),
            "order_date": order.get("order_date")
        } for order in c.get("orders_list", []))
            
        total_system_amount += c_total_amount
        total_system_paid += c_paid_amount
        total_system_orders += c_order_count
        total_system_pending += c_pending_order_count
        total_system_rejects += c_reject_order_count

    total_clients_count = len(clients_with_stats)
    pending_pct = (total_system_pending / total_system_orders * 100) if total_system_orders > 0 else 0.0
    
    dashboard_stats = {
        "total_amount": round(total_system_amount, 2),
        "paid_amount": round(total_system_paid, 2),
        "remaining_amount": round(total_system_amount - total_system_paid, 2),
        "total_clients": total_clients_count,
        "total_clients_percentage": 100.0, 
        "pending_count": total_system_pending,
        "pending_count_percentage": round(pending_pct, 1),
        "reject_count": total_system_rejects, 
        "reject_count_percentage": round((total_system_rejects / total_system_orders * 100), 1) if total_system_orders > 0 else 0.0
    }
    
    country_based_details = list(country_stats_map.values())
    country_split = {c["country_name"]: c["paid_amount"] for c in country_based_details}
    
    return {
        "dashboard_stats": dashboard_stats,
        "country_based_details": country_based_details,
        "country_split": country_split,
        "order_status_details": order_status_details
    }


@router.get("/users/me/details", response_model=ApiResponse[UserDetailResponse])
def get_own_details(current_user: dict = Depends(get_current_user)):
    """
    Get current user profile details including country stats and order statuses.
    """
    # 1. Determine client filter (Admin/Manager see all, Employee see only their own)
    client_match = {}
    if current_user["role"] not in [UserRole.ADMIN, UserRole.MANAGER]:
        client_match = {"client_handler": current_user.get("email")}

    # 2. Fetch data using helper
    dashboard_data = get_user_dashboard_data(client_match)
    
    # 3. Format user profile â€” strip raw binary before JSON serialisation
    user_data = format_mongo_id(current_user.copy())
    user_data["password"] = decrypt_password(user_data.get("password", ""))
    user_data.pop("photo_data", None)
    user_data["photo_url"] = user_data.get("photo_path") or None
    
    # 4. Merge dashboard data into user response
    user_data.update(dashboard_data)
    
    return {
        "status_code": 200,
        "status": "success",
        "message": "User details fetched successfully",
        "data": user_data
    }

@router.get("/users/{email}/details", response_model=ApiResponse[UserDetailResponse])
def get_user_details(email: str, current_user: dict = Depends(require_manager_or_higher)):
    """
    Get profile details of any user including country stats and order statuses.
    Restricted to Admin and Manager.
    """
    target_user = users_collection.find_one({"email": email})
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    # 1. Determine client filter (Admin/Manager viewing an employee - filter by that employee's clients)
    client_match = {"client_handler": target_user.get("email")}

    # 2. Fetch data using helper
    dashboard_data = get_user_dashboard_data(client_match)
    
    # 3. Format target user profile â€” strip raw binary before JSON serialisation
    user_data = format_mongo_id(target_user)
    user_data["password"] = decrypt_password(user_data.get("password", ""))
    user_data.pop("photo_data", None)
    user_data["photo_url"] = user_data.get("photo_path") or None
    
    # 4. Merge dashboard data into user response
    user_data.update(dashboard_data)
    
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Details for {email} fetched successfully",
        "data": user_data
    }

# --- CLIENTS ---

@router.post("/clients", response_model=ApiResponse[ClientResponse], status_code=status.HTTP_201_CREATED)
def create_client(client: ClientCreate, current_user: dict = Depends(get_current_user)):
    # Auto-generate client_id if not provided
    if not client.client_id:
        client.client_id = generate_custom_id("CL", clients_collection, current_user)
    elif clients_collection.find_one({"client_id": client.client_id}):
        raise HTTPException(status_code=400, detail="Client ID already exists")


    client_dict = client.model_dump()
    
    # Dynamic Client Handler logic â€” store EMAIL for uniqueness
    if client_dict.get("client_handler"):
        client_dict["client_handler"] = get_user_email_by_name(client_dict["client_handler"])
    else:
        if current_user["role"] == UserRole.EMPLOYEE:
            client_dict["client_handler"] = current_user.get("email")
        else:
            client_dict["client_handler"] = None
    # Remove display-only field before saving to DB
    client_dict.pop("client_handler_name", None)
            
    # Process base64 photo â€” decode and save to disk
    photo_b64 = client_dict.pop("photo_base64", None)
    client_dict.pop("photo_url", None)  # remove schema field before DB insert
    if photo_b64:
        try:
            import base64
            if "," in photo_b64:
                photo_b64 = photo_b64.split(",")[1]
            photo_bytes = base64.b64decode(photo_b64)
            mime = client_dict.get("photo_mime") or "image/png"
            photo_path = save_bytes_to_file(photo_bytes, mime, "clients")
            client_dict["photo_path"] = photo_path
            client_dict["has_photo"] = True
            client_dict["photo_mime"] = mime
        except Exception:
            client_dict["has_photo"] = False
            client_dict.pop("photo_mime", None)
            
    client_dict["created_at"] = datetime.utcnow()
    result = clients_collection.insert_one(client_dict)
    client_dict["_id"] = str(result.inserted_id)
    invalidate_dashboard_cache()
    

    
    return {
        "status_code": 201,
        "status": "success",
        "message": "Client created successfully",
        "data": client_dict
    }

@router.get("/users/options", response_model=ApiResponse[dict])
def get_user_options(current_user: dict = Depends(get_current_user)):
    """
    Returns profile_names, whatsapp_numbers, and we_chats as flat lists
    for use as dropdown options in the frontend.
    - Admin/Manager: aggregates across ALL users.
    - Employee: returns only their own assigned values.
    """
    if current_user["role"] == UserRole.EMPLOYEE:
        profile_names = current_user.get("profile_names", [])
        we_chats = current_user.get("we_chats", [])
        whatsapp_numbers = current_user.get("whatsapp_numbers", [])
    else:
        employees_data = list(users_collection.find(
            {},
            {"profile_names": 1, "we_chats": 1, "whatsapp_numbers": 1, "_id": 0}
        ))
        profile_names = list({
            p for emp in employees_data
            if isinstance(emp.get("profile_names"), list)
            for p in emp["profile_names"]
        })
        we_chats = list({
            w for emp in employees_data
            if isinstance(emp.get("we_chats"), list)
            for w in emp["we_chats"]
        })
        whatsapp_numbers = list({
            w for emp in employees_data
            if isinstance(emp.get("whatsapp_numbers"), list)
            for w in emp["whatsapp_numbers"]
        })

    return {
        "status_code": 200,
        "status": "success",
        "message": "User options fetched successfully",
        "data": {
            "profile_names": sorted(profile_names),
            "whatsapp_numbers": sorted(whatsapp_numbers),
            "we_chats": sorted(we_chats)
        }
    }


@router.get("/clients", response_model=ApiResponse[list[ClientResponse]])
def get_clients(current_user: dict = Depends(get_current_user)):
    query = {}
    if current_user["role"] == UserRole.EMPLOYEE:
        query = {"client_handler": current_user.get("email")}

    # Dynamic aggregation to pull order_type from associated orders
    pipeline = [
        {"$match": query},
        {
            "$lookup": {
                "from": "orders",
                "localField": "client_id",
                "foreignField": "client_id",
                "as": "client_orders"
            }
        },
        {
            "$addFields": {
                "order_type_list": {
                    "$filter": {
                        "input": "$client_orders.order_type",
                        "as": "ot",
                        "cond": { "$and": [ { "$ne": ["$$ot", None] }, { "$ne": ["$$ot", ""] } ] }
                    }
                },
                "order_id_db": {
                    "$map": {
                        "input": "$client_orders",
                        "as": "order",
                        "in": {"$toString": "$$order._id"}
                    }
                }
            }
        },
        {"$project": {"client_orders": 0}}
    ]
    clients_raw = list(clients_collection.aggregate(pipeline))
    
    for c in clients_raw:
        ot_list = c.pop("order_type_list", [])
        if ot_list:
            counts = {}
            for ot in ot_list:
                counts[ot] = counts.get(ot, 0) + 1
            c["order_type"] = ", ".join([f"{k} : {v}" for k, v in counts.items()])
        else:
            c["order_type"] = ""

    clients = [format_mongo_id(c) for c in clients_raw]
    resolved = resolve_client_handler_bulk(clients)
    
    for c in resolved:
        c.pop("photo_data", None)
        c["photo_url"] = c.get("photo_path") or None
    
    if current_user["role"] == UserRole.EMPLOYEE:
        employee_names = {current_user.get("full_name")}
        profile_names = set(current_user.get("profile_names", []))
        we_chats = set(current_user.get("we_chats", []))
        whatsapp_numbers = set(current_user.get("whatsapp_numbers", []))
    else:
        # Admin/Manager: fetch all employees' data
        employees_data = list(users_collection.find(
            {"role": UserRole.EMPLOYEE}, 
            {"full_name": 1, "profile_names": 1, "we_chats": 1, "whatsapp_numbers": 1, "_id": 0}
        ))
        employee_names = {emp["full_name"] for emp in employees_data if emp.get("full_name")}
        profile_names = {
            p for emp in employees_data 
            if isinstance(emp.get("profile_names"), list) 
            for p in emp["profile_names"]
        }
        we_chats = {
            w for emp in employees_data 
            if isinstance(emp.get("we_chats"), list) 
            for w in emp["we_chats"]
        }
        whatsapp_numbers = {
            w for emp in employees_data 
            if isinstance(emp.get("whatsapp_numbers"), list) 
            for w in emp["whatsapp_numbers"]
        }
                
    # Fetch order types dynamically
    order_type_setting = settings_collection.find_one({"category": SettingCategory.order_type.value})
    order_type_options = order_type_setting.get("options", []) if order_type_setting else ORDER_TYPE_OPTIONS

    detail = {
        "employee_names": list(employee_names),
        "profile_names": list(profile_names),
        "we_chats": list(we_chats),
        "whatsapp_numbers": list(whatsapp_numbers),
        "order_type_options": order_type_options,
        "next_client_id": generate_custom_id("CL", clients_collection, current_user),
        "next_reference_id": generate_custom_id("REF", orders_collection, current_user)
    }

    return {
        "status_code": 200,
        "status": "success",
        "message": "Clients fetched successfully",
        "data": resolved,
        "detail": detail
    }

@router.get("/clients/{client_id}", response_model=ApiResponse[ClientFullResponse])
def get_client(client_id: str, current_user: dict = Depends(require_manager_or_higher)):
    """
    Fetch full client profile including:
    - All client fields
    - Full order list with payment phase details
    - Client photo embedded as base64 (photo_base64 + photo_mime)
    """
    # --- 1. Fetch client ---
    client = clients_collection.find_one({"client_id": client_id})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # --- 2. Inject photo URL (use path stored in DB) ---
    client.pop("photo_data", None)  # remove legacy binary if any
    client["photo_url"] = client.get("photo_path") or None
    client["photo_mime"] = client.get("photo_mime")

    # --- 3. Fetch all orders for this client ---
    raw_orders = list(orders_collection.find({"client_id": client_id}))
    order_ids = [order.get("order_id") for order in raw_orders if order.get("order_id")]
    payments_by_order = {
        payment.get("order_id"): payment
        for payment in payments_collection.find({"order_id": {"$in": order_ids}})
    } if order_ids else {}

    orders_out = []
    for order in raw_orders:
        order_id = order.get("order_id")
        payment = payments_by_order.get(order_id, {})

        # Build order dict with all standard fields
        order_dict = {
            "order_id":                  order.get("order_id"),
            "reference_id":              order.get("reference_id"),
            "order_date":                order.get("order_date"),
            "profile_name":              order.get("profile_name"),
            "title":                     order.get("title"),
            "journal_name":              order.get("journal_name"),
            "order_type":                order.get("order_type"),
            "index":                     order.get("index"),
            "rank":                      order.get("rank"),
            "currency":                  order.get("currency", "USD"),
            "total_amount":              order.get("total_amount", 0.0),
            "writing_amount":            order.get("writing_amount", 0.0),
            "modification_amount":       order.get("modification_amount", 0.0),
            "implementation_amount":     order.get("implementation_amount", 0.0),
            "po_amount":                 order.get("po_amount", 0.0),
            "paid_amount":               payment.get("paid_amount") or order.get("paid_amount", 0.0),
            "payment_status":            order.get("payment_status", "Pending"),
            "order_status":              order.get("order_status"),
            "remarks":                   order.get("remarks"),
            "clients_details":           order.get("clients_details"),
            "client_drive_link":         order.get("client_drive_link"),
            "payment_drive_link":        order.get("payment_drive_link"),
            "writing_start_date":        order.get("writing_start_date"),
            "writing_end_date":          order.get("writing_end_date"),
            "modification_start_date":   order.get("modification_start_date"),
            "modification_end_date":     order.get("modification_end_date"),
            "po_start_date":             order.get("po_start_date"),
            "po_end_date":               order.get("po_end_date"),
            "is_new_order":              order.get("is_new_order"),
            # Payment phases from the payment record
            "phase_1_payment":           payment.get("phase_1_payment", 0.0),
            "phase_1_payment_date":      payment.get("phase_1_payment_date"),
            "phase_1_payment_details":   payment.get("phase_1_payment_details"),
            "phase_2_payment":           payment.get("phase_2_payment", 0.0),
            "phase_2_payment_date":      payment.get("phase_2_payment_date"),
            "phase_2_payment_details":   payment.get("phase_2_payment_details"),
            "phase_3_payment":           payment.get("phase_3_payment", 0.0),
            "phase_3_payment_date":      payment.get("phase_3_payment_date"),
            "phase_3_payment_details":   payment.get("phase_3_payment_details"),
            "phase_1_payment_method":    payment.get("phase_1_payment_method"),
            "phase_2_payment_method":    payment.get("phase_2_payment_method"),
            "phase_3_payment_method":    payment.get("phase_3_payment_method"),
        }
        
        # Inject receipt screenshot URLs for each phase (path stored in DB)
        for phase in (1, 2, 3):
            receipt_path = order.get(f"receipt_phase_{phase}_path")
            receipt_mime = order.get(f"receipt_phase_{phase}_mime", "image/png")
            if receipt_path:
                order_dict[f"receipt_phase_{phase}_url"] = receipt_path
                order_dict[f"receipt_phase_{phase}_mime"] = receipt_mime
            else:
                order_dict[f"receipt_phase_{phase}_url"] = None
                order_dict[f"receipt_phase_{phase}_mime"] = None
        
        orders_out.append(order_dict)

    client["orders"] = orders_out

    # --- 4. Resolve handler name and format _id ---
    client_data = resolve_client_handler(format_mongo_id(client))

    return {
        "status_code": 200,
        "status": "success",
        "message": "Client fetched successfully",
        "data": client_data
    }

@router.delete("/clients/{client_id}", response_model=ApiResponse[dict])
def delete_client(client_id: str, current_user: dict = Depends(require_manager_or_higher)):
    """
    Delete a client and cascade delete all their orders, payments, and manuscripts.
    Restricted to Admin and Manager.
    """
    client = clients_collection.find_one({"client_id": client_id})
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    # Delete client photo if exists
    delete_file_if_exists(client.get("photo_path"))

    # Delete receipts for orders
    orders = list(orders_collection.find({"client_id": client_id}))
    for order in orders:
        for phase in (1, 2, 3):
            delete_file_if_exists(order.get(f"receipt_phase_{phase}_path"))

    # Execute cascade deletion
    orders_result = orders_collection.delete_many({"client_id": client_id})
    payments_result = payments_collection.delete_many({"client_id": client_id})
    payment_history_result = payment_history_collection.delete_many({"client_id": client_id})
    manuscripts_result = manuscripts_collection.delete_many({"client_id": client_id})
    clients_collection.delete_one({"client_id": client_id})
    
    invalidate_dashboard_cache()

    return {
        "status_code": 200,
        "status": "success",
        "message": f"Client deleted along with {orders_result.deleted_count} orders, {payments_result.deleted_count} payments.",
        "data": None
    }

@router.post("/clients/bulk-delete", response_model=ApiResponse[dict])
def bulk_delete_clients(request: ClientBulkDeleteRequest, current_user: dict = Depends(require_manager_or_higher)):
    """
    Bulk delete clients and cascade delete all their orders, payments, and manuscripts.
    Restricted to Admin and Manager.
    """
    deleted_clients = 0
    deleted_orders = 0
    deleted_payments = 0

    for client_id in request.client_ids:
        client = clients_collection.find_one({"client_id": client_id})
        if not client:
            continue

        # Delete client photo if exists
        delete_file_if_exists(client.get("photo_path"))

        # Delete receipts for orders
        orders = list(orders_collection.find({"client_id": client_id}))
        for order in orders:
            for phase in (1, 2, 3):
                delete_file_if_exists(order.get(f"receipt_phase_{phase}_path"))

        # Execute cascade deletion
        o_res = orders_collection.delete_many({"client_id": client_id})
        p_res = payments_collection.delete_many({"client_id": client_id})
        payment_history_collection.delete_many({"client_id": client_id})
        manuscripts_collection.delete_many({"client_id": client_id})
        clients_collection.delete_one({"client_id": client_id})

        deleted_clients += 1
        deleted_orders += o_res.deleted_count
        deleted_payments += p_res.deleted_count
        
    if deleted_clients > 0:
        invalidate_dashboard_cache()

    return {
        "status_code": 200,
        "status": "success",
        "message": f"Successfully deleted {deleted_clients} clients, {deleted_orders} orders, and {deleted_payments} payments.",
        "data": None
    }

@router.post("/clients/assign", response_model=ApiResponse[ClientResponse])
def assign_client(request: ClientAssignRequest, current_user: dict = Depends(require_manager_or_higher)):
    """
    Assign an Employee to a Client.
    Restricted to Admin and Manager.
    """
    # 1. Verify Employee
    employee = users_collection.find_one({"email": request.employee_email, "role": UserRole.EMPLOYEE})
    if not employee:
        raise HTTPException(
            status_code=404, 
            detail=f"Employee with email {request.employee_email} not found"
        )
    
    # 2. Verify Client
    client = clients_collection.find_one({"client_id": request.client_id})
    if not client:
        raise HTTPException(
            status_code=404, 
            detail=f"Client with ID {request.client_id} not found"
        )
    
    # 3. Update Client Handler â€” store email for uniqueness
    clients_collection.update_one(
        {"client_id": request.client_id},
        {"$set": {"client_handler": employee.get("email")}}
    )
    

    
    # Fetch updated client
    updated_client = clients_collection.find_one({"client_id": request.client_id})
    
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Client {request.client_id} assigned to {employee.get('full_name')}",
        "data": resolve_client_handler(format_mongo_id(updated_client))
    }

# --- MANUSCRIPTS ---

@router.post("/manuscripts", response_model=ApiResponse[ManuscriptResponse], status_code=status.HTTP_201_CREATED)
def create_manuscript(manuscript: ManuscriptCreate, current_user: dict = Depends(require_manager_or_higher)):
    # Verify client exists
    if not clients_collection.find_one({"client_id": manuscript.client_id}):
        raise HTTPException(status_code=400, detail="Invalid client_id")
    
    ms_dict = manuscript.model_dump()
    ms_dict["created_at"] = datetime.utcnow()
    result = manuscripts_collection.insert_one(ms_dict)
    ms_dict["_id"] = str(result.inserted_id)

    
    return {
        "status_code": 201,
        "status": "success",
        "message": "Manuscript created successfully",
        "data": ms_dict
    }

@router.get("/manuscripts", response_model=ApiResponse[list[ManuscriptResponse]])
def get_manuscripts(current_user: dict = Depends(get_current_user)):
    query = {}
    if current_user["role"] == UserRole.EMPLOYEE:
        my_client_ids = clients_collection.distinct("client_id", {"client_handler": current_user.get("email")})
        query = {"client_id": {"$in": my_client_ids}} if my_client_ids else {"client_id": {"$in": []}}
        
    ms = list(manuscripts_collection.find(query))
    return {
        "status_code": 200,
        "status": "success",
        "message": "Manuscripts fetched successfully",
        "data": [format_mongo_id(m) for m in ms]
    }

# --- ORDERS ---

@router.post("/orders", response_model=ApiResponse[OrderResponse], status_code=status.HTTP_201_CREATED)
def create_order(order: OrderCreate, current_user: dict = Depends(require_manager_or_higher)):
    # Verify client exists
    if not clients_collection.find_one({"client_id": order.client_id}):
        raise HTTPException(status_code=400, detail="Invalid client_id")
    
    # Manuscript is optional â€” only validate if provided
    if order.manuscript_id:
        if not manuscripts_collection.find_one({"manuscript_id": order.manuscript_id}):
            raise HTTPException(status_code=400, detail="Invalid manuscript_id")
    
    # Auto-generate reference_id if not provided
    if not order.reference_id:
        order.reference_id = generate_custom_id("REF", orders_collection, current_user)
    elif orders_collection.find_one({"reference_id": order.reference_id}):
        raise HTTPException(status_code=400, detail="This reference ID already exists")

    
    order_dict = order.model_dump()
    
    # Auto-update is_new_order based on existing orders
    existing_orders_count = orders_collection.count_documents({"client_id": order.client_id})
    if existing_orders_count > 1:
        order_dict["is_new_order"] = "no"
        orders_collection.update_many({"client_id": order.client_id}, {"$set": {"is_new_order": "no"}})
    else:
        order_dict["is_new_order"] = "yes"
        
    order_dict["created_at"] = datetime.utcnow()
    order_dict["updated_at"] = datetime.utcnow()
    result = orders_collection.insert_one(order_dict)
    order_dict["_id"] = str(result.inserted_id)
    invalidate_dashboard_cache()
    

    
    return {
        "status_code": 201,
        "status": "success",
        "message": "Order created successfully",
        "data": order_dict
    }

@router.get("/orders", response_model=ApiResponse[list[OrderResponse]])
def get_orders(current_user: dict = Depends(get_current_user)):
    query = {}
    if current_user["role"] == UserRole.EMPLOYEE:
        my_client_ids = clients_collection.distinct("client_id", {"client_handler": current_user.get("email")})
        query = {"client_id": {"$in": my_client_ids}} if my_client_ids else {"client_id": {"$in": []}}
        
    orders = list(orders_collection.find(query))
    return {
        "status_code": 200,
        "status": "success",
        "message": "Orders fetched successfully",
        "data": [format_mongo_id(o) for o in orders]
    }

# --- PAYMENTS ---

@router.post("/payments", response_model=ApiResponse[PaymentResponse], status_code=status.HTTP_201_CREATED)
def create_payment(payment: PaymentCreate, current_user: dict = Depends(require_manager_or_higher)):
    if not clients_collection.find_one({"client_id": payment.client_id}):
        raise HTTPException(status_code=400, detail="Invalid client_id")
    
    pay_dict = payment.model_dump()
    pay_dict["created_at"] = datetime.utcnow()
    result = payments_collection.insert_one(pay_dict)
    pay_dict["_id"] = str(result.inserted_id)
    invalidate_dashboard_cache()
    

    
    return {
        "status_code": 201,
        "status": "success",
        "message": "Payment created successfully",
        "data": pay_dict
    }

@router.get("/payments", response_model=ApiResponse[list[PaymentResponse]])
def get_payments(current_user: dict = Depends(get_current_user)):
    query = {}
    if current_user["role"] == UserRole.EMPLOYEE:
        my_client_ids = clients_collection.distinct("client_id", {"client_handler": current_user.get("email")})
        query = {"client_id": {"$in": my_client_ids}} if my_client_ids else {"client_id": {"$in": []}}
        
    payments = list(payments_collection.find(query))
    return {
        "status_code": 200,
        "status": "success",
        "message": "Payments fetched successfully",
        "data": [format_mongo_id(p) for p in payments]
    }

@router.get("/payments/history", response_model=ApiResponse[list[PaymentHistoryItem]])
def get_payment_history(
    client_id: Optional[str] = None, 
    order_id: Optional[str] = None, 
    page: int = Query(1, ge=1),
    limit: int = Query(15, ge=1, le=100),
    search: Optional[str] = Query(None),
    date_filter: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Detailed payment history from the flattened payment_history_collection.
    """
    query = {}
    if current_user["role"] == UserRole.EMPLOYEE:
        # Filter by clients handled by this employee
        my_client_ids = clients_collection.distinct("client_id", {"client_handler": current_user.get("email")})
        query["client_id"] = {"$in": my_client_ids}
    
    if client_id:
        query["client_id"] = client_id
    if order_id:
        query["order_id"] = order_id

    if search:
        search_regex = {"$regex": search, "$options": "i"}
        query["$or"] = [
            {"client_id": search_regex},
            {"reference_id": search_regex},
            {"ref_no": search_regex},
            {"order_id": search_regex},
            {"order_db_id": search_regex},
            {"manuscript_id": search_regex}
        ]

    if date_filter and date_filter != 'all':
        now = datetime.utcnow()
        date_query = None
        
        if date_filter == 'lastWeek':
            last_week = now - timedelta(days=7)
            date_query = {"$gte": last_week, "$lte": now}
        elif date_filter == 'lastMonth':
            last_month = now - timedelta(days=30)
            date_query = {"$gte": last_month, "$lte": now}
        elif date_filter == 'custom' and start_date and end_date:
            # Set to start/end of day
            s_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            e_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            date_query = {"$gte": s_date, "$lte": e_date}
            
        if date_query:
            if "$or" in query:
                # If there's already an $or (from search), use $and to combine
                existing_or = query.pop("$or")
                query["$and"] = [
                    {"$or": existing_or},
                    {"$or": [
                        {"phase_1_payment_date": date_query},
                        {"phase_2_payment_date": date_query},
                        {"phase_3_payment_date": date_query}
                    ]}
                ]
            else:
                query["$or"] = [
                    {"phase_1_payment_date": date_query},
                    {"phase_2_payment_date": date_query},
                    {"phase_3_payment_date": date_query}
                ]

    total_items = payment_history_collection.count_documents(query)
    total_pages = (total_items + limit - 1) // limit if limit > 0 else 0
    skip = (page - 1) * limit

    pipeline = [
        {"$match": query},
        {"$sort": {"created_at": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {
            "$lookup": {
                "from": "orders",
                "localField": "order_id",
                "foreignField": "order_id",
                "as": "order_info"
            }
        },
        {
            "$addFields": {
                "currency": {
                    "$cond": {
                        "if": {"$gt": [{"$size": "$order_info"}, 0]},
                        "then": {"$arrayElemAt": ["$order_info.currency", 0]},
                        "else": "USD"
                    }
                }
            }
        },
        {
            "$project": {
                "order_info": 0
            }
        }
    ]

    history = list(payment_history_collection.aggregate(pipeline))

    pagination_meta = {
        "current_page": page,
        "limit": limit,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }
    
    return {
        "status_code": 200,
        "status": "success",
        "message": "Payment history fetched successfully",
        "data": history,
        "pagination": pagination_meta
    }

@router.get("/payments/pending-summary", response_model=ApiResponse[PendingSummaryResponse])
def get_pending_payment_summary(current_user: dict = Depends(require_manager_or_higher)):
    """
    Summary of pending payments across all clients and orders.
    Restricted to Manager and Admin.
    """
    from app.currency_converter import get_all_inr_rates
    rates = get_all_inr_rates()
    usd_rate = rates.get("USD", 0.012)
    cny_rate = rates.get("CNY", 0.087)
    aed_rate = rates.get("AED", 0.044)
    sar_rate = rates.get("SAR", 0.045)
    
    multipliers = {
        "USD": 1.0,
        "INR": usd_rate,
        "CNY": usd_rate / cny_rate if cny_rate else 0.14,
        "AED": usd_rate / aed_rate if aed_rate else 0.272,
        "SAR": usd_rate / sar_rate if sar_rate else 0.267,
    }

    pipeline = [
        {"$match": {"order_status": {"$ne": "Inactive"}}},
        {
            "$addFields": {
                "total_usd": {
                    "$switch": {
                        "branches": [
                            {"case": {"$eq": [{"$toUpper": "$currency"}, "INR"]}, "then": {"$multiply": ["$total_amount", multipliers["INR"]]}},
                            {"case": {"$eq": [{"$toUpper": "$currency"}, "CNY"]}, "then": {"$multiply": ["$total_amount", multipliers["CNY"]]}},
                            {"case": {"$eq": [{"$toUpper": "$currency"}, "AED"]}, "then": {"$multiply": ["$total_amount", multipliers["AED"]]}},
                            {"case": {"$eq": [{"$toUpper": "$currency"}, "SAR"]}, "then": {"$multiply": ["$total_amount", multipliers["SAR"]]}}
                        ],
                        "default": "$total_amount"
                    }
                },
                "paid_usd": {
                    "$switch": {
                        "branches": [
                            {"case": {"$eq": [{"$toUpper": "$currency"}, "INR"]}, "then": {"$multiply": [{"$ifNull": ["$paid_amount", 0.0]}, multipliers["INR"]]}},
                            {"case": {"$eq": [{"$toUpper": "$currency"}, "CNY"]}, "then": {"$multiply": [{"$ifNull": ["$paid_amount", 0.0]}, multipliers["CNY"]]}},
                            {"case": {"$eq": [{"$toUpper": "$currency"}, "AED"]}, "then": {"$multiply": [{"$ifNull": ["$paid_amount", 0.0]}, multipliers["AED"]]}},
                            {"case": {"$eq": [{"$toUpper": "$currency"}, "SAR"]}, "then": {"$multiply": [{"$ifNull": ["$paid_amount", 0.0]}, multipliers["SAR"]]}}
                        ],
                        "default": {"$ifNull": ["$paid_amount", 0.0]}
                    }
                }
            }
        },
        {
            "$addFields": {
                "remaining_usd": {"$subtract": ["$total_usd", "$paid_usd"]}
            }
        },
        {"$match": {"remaining_usd": {"$gt": 0}}},
        {
            "$group": {
                "_id": "$client_id",
                "pending_orders": {"$sum": 1},
                "total_pending_amount": {"$sum": "$remaining_usd"}
            }
        },
        {
            "$lookup": {
                "from": "clients",
                "localField": "_id",
                "foreignField": "client_id",
                "as": "client_info"
            }
        },
        {"$unwind": "$client_info"},
        {
            "$project": {
                "_id": 0,
                "client_id": "$_id",
                "client_name": "$client_info.name",
                "total_orders": "$client_info.total_orders",
                "pending_orders": 1,
                "total_pending_amount": 1
            }
        },
        {"$sort": {"total_pending_amount": -1}}
    ]
    
    pending_clients = list(orders_collection.aggregate(pipeline))
    
    total_pending_amount = sum(c["total_pending_amount"] for c in pending_clients)
    pending_orders_count = sum(c["pending_orders"] for c in pending_clients)
    pending_clients_count = len(pending_clients)
    
    return {
        "status_code": 200,
        "status": "success",
        "message": "Pending payment summary fetched successfully",
        "data": {
            "total_pending_amount": round(total_pending_amount, 2),
            "pending_orders_count": pending_orders_count,
            "pending_clients_count": pending_clients_count,
            "top_pending_clients": pending_clients[:10]  # Top 10 for overview
        }
    }

# --- SETTINGS ---

@router.get("/settings", response_model=ApiResponse[LookupSettingsData])
def get_all_settings(current_user: dict = Depends(get_current_user)):
    """Fetch all settings grouped in a single document."""
    settings = settings_collection.find_one({"key": "lookup_settings"})
    if not settings:
        settings = {}
        
    # Filter out MongoDB internal fields
    data = {k: v for k, v in settings.items() if k not in ["_id", "key"]}
    
    return {
        "status_code": 200,
        "status": "success",
        "message": "All settings fetched successfully",
        "data": data
    }

@router.get("/settings/{category}", response_model=ApiResponse[list[Any]])
def get_setting_category(category: SettingCategory, current_user: dict = Depends(get_current_user)):
    """Fetch options for a specific setting category."""
    settings = settings_collection.find_one({"key": "lookup_settings"})
    options = settings.get(category.value, []) if settings else []
    
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Category '{category.value}' fetched successfully",
        "data": options
    }

@router.post("/settings/{category}/add", response_model=ApiResponse[dict])
def add_setting_option(category: SettingCategory, action: SettingItemAction, current_user: dict = Depends(require_manager_or_higher)):
    """Add a new option to a setting category."""
    if not action.option or (isinstance(action.option, str) and not action.option.strip()):
        raise HTTPException(status_code=400, detail="Option cannot be empty")
        
    value_to_add = action.option.strip() if isinstance(action.option, str) else action.option
        
    result = settings_collection.update_one(
        {"key": "lookup_settings"},
        {"$addToSet": {category.value: value_to_add}},
        upsert=True
    )
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Added option to '{category.value}'",
        "data": None
    }

@router.delete("/settings/{category}/remove", response_model=ApiResponse[dict])
def remove_setting_option(category: SettingCategory, action: SettingItemAction, current_user: dict = Depends(require_manager_or_higher)):
    """Remove an option from a setting category."""
    value_to_remove = action.option.strip() if isinstance(action.option, str) else action.option
    result = settings_collection.update_one(
        {"key": "lookup_settings"},
        {"$pull": {category.value: value_to_remove}}
    )
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Option not found in category")
        
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Removed option from '{category.value}'",
        "data": None
    }

@router.put("/settings/{category}/update", response_model=ApiResponse[dict])
def update_setting_option(category: SettingCategory, action: SettingItemUpdateAction, current_user: dict = Depends(require_manager_or_higher)):
    """Update an existing option in a setting category."""
    if not action.new_option or (isinstance(action.new_option, str) and not action.new_option.strip()):
        raise HTTPException(status_code=400, detail="New option cannot be empty")
        
    old_val = action.old_option.strip() if isinstance(action.old_option, str) else action.old_option
    new_val = action.new_option.strip() if isinstance(action.new_option, str) else action.new_option
    
    result = settings_collection.update_one(
        {"key": "lookup_settings", category.value: old_val},
        {
            "$set": {f"{category.value}.$": new_val}
        }
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=404, detail="Option not found or no changes made")
        
    return {
        "status_code": 200,
        "status": "success",
        "message": f"Updated option in '{category.value}'",
        "data": None
    }

# --- BANK ACCOUNTS ---

@router.get("/bank-accounts", response_model=ApiResponse[list[BankAccountResponse]])
def get_bank_accounts(current_user: dict = Depends(get_current_user)):
    """Get all bank accounts."""
    accounts = list(bank_accounts_collection.find())
    for acc in accounts:
        acc["_id"] = str(acc["_id"])
    return {
        "status_code": 200,
        "status": "success",
        "message": "Bank accounts fetched successfully",
        "data": accounts
    }

@router.post("/bank-accounts", response_model=ApiResponse[BankAccountResponse])
def create_bank_account(data: BankAccountCreate, current_user: dict = Depends(require_manager_or_higher)):
    """Create a new bank account."""
    if bank_accounts_collection.find_one({"account_number": data.account_number}):
        raise HTTPException(status_code=400, detail="Bank account already exists")
    
    acc_dict = data.model_dump()
    acc_dict["created_at"] = datetime.utcnow()
    result = bank_accounts_collection.insert_one(acc_dict)
    
    acc_dict["_id"] = str(result.inserted_id)
    return {
        "status_code": 201,
        "status": "success",
        "message": "Bank account created successfully",
        "data": acc_dict
    }

@router.put("/bank-accounts/{account_id}", response_model=ApiResponse[BankAccountResponse])
def update_bank_account(account_id: str, data: BankAccountUpdate, current_user: dict = Depends(require_manager_or_higher)):
    """Update a bank account."""
    if not ObjectId.is_valid(account_id):
        raise HTTPException(status_code=400, detail="Invalid bank account ID")
        
    existing = bank_accounts_collection.find_one({"_id": ObjectId(account_id)})
    if not existing:
        raise HTTPException(status_code=404, detail="Bank account not found")
        
    # Check if new number already exists
    if existing["account_number"] != data.account_number:
        if bank_accounts_collection.find_one({"account_number": data.account_number}):
            raise HTTPException(status_code=400, detail="Bank account number already exists")
            
    bank_accounts_collection.update_one(
        {"_id": ObjectId(account_id)},
        {"$set": {"account_number": data.account_number}}
    )
    
    updated = bank_accounts_collection.find_one({"_id": ObjectId(account_id)})
    updated["_id"] = str(updated["_id"])
    return {
        "status_code": 200,
        "status": "success",
        "message": "Bank account updated successfully",
        "data": updated
    }

@router.delete("/bank-accounts/{account_id}", response_model=ApiResponse[dict])
def delete_bank_account(account_id: str, current_user: dict = Depends(require_manager_or_higher)):
    """Delete a bank account."""
    if not ObjectId.is_valid(account_id):
        raise HTTPException(status_code=400, detail="Invalid bank account ID")
        
    result = bank_accounts_collection.delete_one({"_id": ObjectId(account_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Bank account not found")
        
    return {
        "status_code": 200,
        "status": "success",
        "message": "Bank account deleted successfully",
        "data": None
    }

# --- DASHBOARD ---

@router.get("/dashboard/orders", response_model=ApiResponse[list[DashboardOrderResponse]])
def get_dashboard_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(15, ge=1, le=100),
    search: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    order_status: Optional[str] = Query(None),
    rank: Optional[str] = Query(None),
    index: Optional[str] = Query(None),
    client_country: Optional[str] = Query(None),
    client_handler_name: Optional[str] = Query(None),
    is_new_order: Optional[str] = Query(None),
    order_type: Optional[str] = Query(None),
    we_chat: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_order: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Unified endpoint for the frontend dashboard.
    Optimized with MongoDB Aggregation Pipeline ($lookup + $unwind).
    Shows clients even if no orders exist.
    Includes caching for improved performance.
    """
    cache_key = dashboard_cache_key(current_user.get("email", "anonymous"), current_user.get("role", "unknown"))
    cached_data = cache_manager.get(cache_key)
    
    def _filter_and_paginate(data_list):
        filter_options = {
            "payment_status": sorted(list(set(str(r.get("payment_status", "")).strip().upper() for r in data_list if str(r.get("payment_status", "")).strip()))),
            "order_status": sorted(list(set(str(r.get("order_status", "")).strip().upper() for r in data_list if str(r.get("order_status", "")).strip()))),
            "rank": sorted(list(set(str(r.get("rank", "")).strip().upper() for r in data_list if str(r.get("rank", "")).strip()))),
            "index": sorted(list(set(str(r.get("index", "")).strip().upper() for r in data_list if str(r.get("index", "")).strip()))),
            "client_country": sorted(list(set(str(r.get("client_country", "")).strip().upper() for r in data_list if str(r.get("client_country", "")).strip()))),
            "client_handler_name": sorted(list(set(str(r.get("client_handler_name", "")).strip().upper() for r in data_list if str(r.get("client_handler_name", "")).strip()))),
            "is_new_order": sorted(list(set(str(r.get("is_new_order", "")).strip().upper() for r in data_list if str(r.get("is_new_order", "")).strip()))),
            "order_type": sorted(list(set(str(r.get("order_type", "")).strip().upper() for r in data_list if str(r.get("order_type", "")).strip()))),
            "we_chat": sorted(list(set(str(r.get("we_chat", "")).strip().upper() for r in data_list if str(r.get("we_chat", "")).strip())))
        }

        filtered = []
        s = search.lower() if search else None
        
        for row in data_list:
            if s:
                search_fields = [
                    str(row.get("client_name", "")),
                    str(row.get("client_id", "")),
                    str(row.get("order_id", "")),
                    str(row.get("reference_id", "")),
                    str(row.get("journal_name", "")),
                    str(row.get("title", ""))
                ]
                if not any(s in sf.lower() for sf in search_fields if sf):
                    continue
            
            if payment_status and str(row.get("payment_status", "")).strip().lower() != payment_status.strip().lower(): continue
            if order_status and str(row.get("order_status", "")).strip().lower() != order_status.strip().lower(): continue
            if rank and str(row.get("rank", "")).strip().lower() != rank.strip().lower(): continue
            if index and str(row.get("index", "")).strip().lower() != index.strip().lower(): continue
            if client_country and str(row.get("client_country", "")).strip().lower() != client_country.strip().lower(): continue
            if client_handler_name and str(row.get("client_handler_name", "")).strip().lower() != client_handler_name.strip().lower(): continue
            if is_new_order and str(row.get("is_new_order", "")).strip().lower() != is_new_order.strip().lower(): continue
            if order_type and str(row.get("order_type", "")).strip().lower() != order_type.strip().lower(): continue
            if we_chat and str(row.get("we_chat", "")).strip().lower() != we_chat.strip().lower(): continue
            
            filtered.append(row)

        # --- Date-field sorting ---
        if sort_by and sort_by in ALLOWED_DATE_SORT_FIELDS and sort_order in ("asc", "desc"):
            reverse = sort_order == "desc"
            filtered = sorted(
                filtered,
                key=lambda row: _to_date_key(row.get(sort_by)),
                reverse=reverse,
            )

        total_items = len(filtered)
        total_pages = (total_items + limit - 1) // limit if limit > 0 else 0
        skip = (page - 1) * limit
        paginated = filtered[skip : skip + limit]
        
        pagination_meta = {
            "current_page": page,
            "limit": limit,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1
        }
        return paginated, pagination_meta, filter_options
    
    # Helper to build detail
    def _build_dashboard_detail(filter_options=None):
        if current_user["role"] == UserRole.EMPLOYEE:
            employee_names = {current_user.get("full_name")}
            profile_names = set(current_user.get("profile_names", []))
            we_chats = set(current_user.get("we_chats", []))
            whatsapp_numbers = set(current_user.get("whatsapp_numbers", []))
        else:
            employees_data = list(users_collection.find(
                {}, 
                {"full_name": 1, "profile_names": 1, "we_chats": 1, "whatsapp_numbers": 1, "_id": 0}
            ))
            employee_names = {emp["full_name"] for emp in employees_data if emp.get("full_name")}
            profile_names = {p for emp in employees_data if isinstance(emp.get("profile_names"), list) for p in emp["profile_names"]}
            we_chats = {w for emp in employees_data if isinstance(emp.get("we_chats"), list) for w in emp["we_chats"]}
            whatsapp_numbers = {w for emp in employees_data if isinstance(emp.get("whatsapp_numbers"), list) for w in emp["whatsapp_numbers"]}
            
        settings = settings_collection.find_one({"key": "lookup_settings"}) or {}
        order_type_options = settings.get(SettingCategory.order_type.value, ORDER_TYPE_OPTIONS)
        bank_account_options = settings.get(SettingCategory.bank_account.value, [])
        
        return {
            "employee_names": list(employee_names),
            "profile_names": list(profile_names),
            "we_chats": list(we_chats),
            "whatsapp_numbers": list(whatsapp_numbers),
            "order_type_options": order_type_options,
            "bank_account_options": bank_account_options,
            "filter_options": filter_options or {}
        }

    if cached_data is not None:
        paginated_data, pagination_meta, filter_opts = _filter_and_paginate(cached_data)
        return {
            "status_code": 200,
            "status": "success",
            "message": "Dashboard data fetched successfully",
            "data": paginated_data,
            "pagination": pagination_meta,
            "detail": _build_dashboard_detail(filter_opts)
        }

    # 1. Get filtered clients query
    client_match = {}
    if current_user["role"] == UserRole.EMPLOYEE:
        client_match = {"client_handler": current_user.get("email")}
        
    # 2. Aggregation Pipeline
    pipeline = [
        {"$match": client_match},
        {
            "$lookup": {
                "from": "orders",
                "localField": "client_id",
                "foreignField": "client_id",
                "as": "order"
            }
        },
        # Join clients with their orders; keep clients with 0 orders (placeholder row)
        {"$unwind": {"path": "$order", "preserveNullAndEmptyArrays": True}},
        {
            "$lookup": {
                "from": "payments",
                "localField": "order.order_id",
                "foreignField": "order_id",
                "as": "p_list"
            }
        },
        {
            "$project": {
                "_id": 0,
                "order_db_id": {"$cond": [{"$ifNull": ["$order._id", False]}, {"$toString": "$order._id"}, None]},
                "order_id": "$order.order_id",
                "s_no": "$order.s_no",
                "order_date": "$order.order_date",
                "client_id": "$client_id",
                "client_name": "$name",
                "client_country": "$country",
                "client_Email": "$email",
                "client_whatsapp_number": "$whatsapp_no",
                "reference_id": "$order.reference_id",
                "ref_no": {"$ifNull": ["$order.client_ref_no", "$client_ref_no"]},
                "manuscript_id": "$order.manuscript_id",
                "journal_name": "$order.journal_name",
                "title": "$order.title",
                "order_type": "$order.order_type",
                "index": "$order.index",
                "rank": "$order.rank",
                "currency": {"$ifNull": ["$order.currency", "USD"]},
                "total_amount": {"$ifNull": ["$order.total_amount", 0.0]},
                "writing_amount": {"$ifNull": ["$order.writing_amount", 0.0]},
                "modification_amount": {"$ifNull": ["$order.modification_amount", 0.0]},
                "implementation_amount": {"$ifNull": ["$order.implementation_amount", 0.0]},
                "po_amount": {"$ifNull": ["$order.po_amount", 0.0]},
                "writing_start_date": "$order.writing_start_date",
                "writing_end_date": "$order.writing_end_date",
                "modification_start_date": "$order.modification_start_date",
                "modification_end_date": "$order.modification_end_date",
                "po_start_date": "$order.po_start_date",
                "po_end_date": "$order.po_end_date",
                "implementation_start_date": "$order.implementation_start_date",
                "implementation_end_date": "$order.implementation_end_date",
                "phase": {"$literal": None},
                # All phase fields live in a single payment doc per order â€” read directly
                "phase_1_payment": {"$arrayElemAt": ["$p_list.phase_1_payment", 0]},
                "phase_1_payment_date": {"$arrayElemAt": ["$p_list.phase_1_payment_date", 0]},
                "phase_1_payment_details": {"$arrayElemAt": ["$p_list.phase_1_payment_details", 0]},
                "phase_2_payment": {"$arrayElemAt": ["$p_list.phase_2_payment", 0]},
                "phase_2_payment_date": {"$arrayElemAt": ["$p_list.phase_2_payment_date", 0]},
                "phase_2_payment_details": {"$arrayElemAt": ["$p_list.phase_2_payment_details", 0]},
                "phase_3_payment": {"$arrayElemAt": ["$p_list.phase_3_payment", 0]},
                "phase_3_payment_date": {"$arrayElemAt": ["$p_list.phase_3_payment_date", 0]},
                "phase_3_payment_details": {"$arrayElemAt": ["$p_list.phase_3_payment_details", 0]},
                "phase_1_payment_method": {"$arrayElemAt": ["$p_list.phase_1_payment_method", 0]},
                "phase_2_payment_method": {"$arrayElemAt": ["$p_list.phase_2_payment_method", 0]},
                "phase_3_payment_method": {"$arrayElemAt": ["$p_list.phase_3_payment_method", 0]},
                "payment_status": {"$ifNull": ["$order.payment_status", "No Order"]},
                "paid_amount": {"$ifNull": ["$order.paid_amount", {"$ifNull": [{"$arrayElemAt": ["$p_list.paid_amount", 0]}, 0.0]}]},
                "client_link": "$client_link",
                "bank_account": "$bank_account",
                "receive_bank_account": "$order.receive_bank_account",
                "client_affiliations": "$affiliation",
                "client_handler": "$client_handler",
                "profile_name": "$order.profile_name",
                # orders.whatsapp_number = the employee profile WA used for this order
                "profile_whatsapp_number": "$order.whatsapp_number",
                "whatsapp_number": "$order.whatsapp_number",
                "we_chat": "$order.we_chat",
                "remarks": "$order.remarks",
                "order_status": "$order.order_status",
                "clients_details": "$order.clients_details",
                "client_drive_link": {"$ifNull": ["$order.client_drive_link", "$client_drive_link"]},
                "payment_drive_link": {"$ifNull": ["$order.payment_drive_link", "$payment_drive_link"]},
                "is_new_order": {"$ifNull": ["$order.is_new_order", "yes"]}
            }
        }
    ]
    
    from concurrent.futures import ThreadPoolExecutor
    
    dashboard_whatsapp_numbers = []
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_dashboard = executor.submit(lambda: list(clients_collection.aggregate(pipeline)))
        
        if current_user["role"] == UserRole.EMPLOYEE:
            dashboard_whatsapp_numbers = list(set(current_user.get("whatsapp_numbers", []) or []))
            dashboard_data = future_dashboard.result()
        else:
            future_employees = executor.submit(
                lambda: list(users_collection.find(
                    {"role": UserRole.EMPLOYEE},
                    {"whatsapp_numbers": 1, "_id": 0}
                ))
            )
            dashboard_data = future_dashboard.result()
            employees_data = future_employees.result()
            dashboard_whatsapp_numbers = list({
                w for emp in employees_data
                if isinstance(emp.get("whatsapp_numbers"), list)
                for w in emp["whatsapp_numbers"]
            })

    # Resolve handler names for display in bulk
    resolve_client_handler_bulk(dashboard_data)

    # Attach client photo URL for each row
    client_ids = list({row["client_id"] for row in dashboard_data if row.get("client_id")})
    photo_map = {}
    for client_doc in clients_collection.find(
        {"client_id": {"$in": client_ids}},
        {"client_id": 1, "photo_path": 1, "photo_mime": 1}
    ):
        photo_map[client_doc["client_id"]] = {
            "photo_url":  client_doc.get("photo_path") or None,
            "photo_mime": client_doc.get("photo_mime")
        }

    # Attach receipt screenshot URLs for each row
    # Collect all order_db_ids
    order_db_ids = list({row["order_db_id"] for row in dashboard_data if row.get("order_db_id")})
    receipt_map = {}  # Maps order_db_id -> {phase -> {url, mime}}
    
    if order_db_ids:
        # Convert string IDs back to ObjectId for querying
        order_object_ids = []
        for oid_str in order_db_ids:
            try:
                order_object_ids.append(ObjectId(oid_str))
            except:
                pass
        
        # Query orders for receipt path fields only (no binary data needed)
        for order_doc in orders_collection.find(
            {"_id": {"$in": order_object_ids}},
            {
                "_id": 1,
                "receipt_phase_1_path": 1, "receipt_phase_1_mime": 1,
                "receipt_phase_2_path": 1, "receipt_phase_2_mime": 1,
                "receipt_phase_3_path": 1, "receipt_phase_3_mime": 1
            }
        ):
            order_id_str = str(order_doc["_id"])
            receipt_map[order_id_str] = {}
            
            for phase in (1, 2, 3):
                receipt_path = order_doc.get(f"receipt_phase_{phase}_path")
                receipt_mime = order_doc.get(f"receipt_phase_{phase}_mime", "image/png")
                
                if receipt_path:
                    receipt_map[order_id_str][phase] = {
                        "url": receipt_path,
                        "mime": receipt_mime
                    }
                else:
                    receipt_map[order_id_str][phase] = {
                        "url": None,
                        "mime": None
                    }

    from app.currency_converter import get_all_inr_rates
    rates = get_all_inr_rates(allow_live_fetch=False)
    usd_rate = rates.get("USD", 0.012)
    cny_rate = rates.get("CNY", 0.087)
    aed_rate = rates.get("AED", 0.044)
    sar_rate = rates.get("SAR", 0.045)
    
    multipliers = {
        "USD": 1.0,
        "INR": usd_rate,
        "CNY": usd_rate / cny_rate if cny_rate else 0.14,
        "AED": usd_rate / aed_rate if aed_rate else 0.272,
        "SAR": usd_rate / sar_rate if sar_rate else 0.267,
    }

    for row in dashboard_data:
        info = photo_map.get(row.get("client_id"), {})
        row["client_photo_url"]  = info.get("photo_url")
        row["client_photo_mime"] = info.get("photo_mime")
        row["whatsapp_numbers"] = dashboard_whatsapp_numbers
        
        # Inject receipt screenshot URLs for this order
        order_id_str = row.get("order_db_id")
        if order_id_str and order_id_str in receipt_map:
            for phase in (1, 2, 3):
                phase_receipt = receipt_map[order_id_str].get(phase, {})
                row[f"receipt_phase_{phase}_url"]  = phase_receipt.get("url")
                row[f"receipt_phase_{phase}_mime"] = phase_receipt.get("mime")
        else:
            # No receipts for this order
            for phase in (1, 2, 3):
                row[f"receipt_phase_{phase}_url"]  = None
                row[f"receipt_phase_{phase}_mime"] = None
        
        # Calculate USD equivalents dynamically
        curr = (row.get("currency") or "USD").upper().strip()
        multiplier = multipliers.get(curr, 1.0)
        
        raw_total = row.get("total_amount") or 0.0
        raw_paid = row.get("paid_amount") or 0.0
        
        row["total_amount_usd"] = round(raw_total * multiplier, 2)
        row["paid_amount_usd"] = round(raw_paid * multiplier, 2)

    cache_manager.set(cache_key, dashboard_data)

    if current_user["role"] == UserRole.EMPLOYEE:
        employee_names = {current_user.get("full_name")}
        profile_names = set(current_user.get("profile_names", []))
        we_chats = set(current_user.get("we_chats", []))
        whatsapp_numbers = set(current_user.get("whatsapp_numbers", []))
    else:
        # Optimized retrieval of all users for admin/manager detail options
        employees_data = list(users_collection.find(
            {}, 
            {"full_name": 1, "profile_names": 1, "we_chats": 1, "whatsapp_numbers": 1, "_id": 0}
        ))
        employee_names = {emp["full_name"] for emp in employees_data if emp.get("full_name")}
        profile_names = {
            p for emp in employees_data 
            if isinstance(emp.get("profile_names"), list) 
            for p in emp["profile_names"]
        }
        we_chats = {
            w for emp in employees_data 
            if isinstance(emp.get("we_chats"), list) 
            for w in emp["we_chats"]
        }
        whatsapp_numbers = {
            w for emp in employees_data 
            if isinstance(emp.get("whatsapp_numbers"), list) 
            for w in emp["whatsapp_numbers"]
        }

    # Fetch order types dynamically
    settings = settings_collection.find_one({"key": "lookup_settings"}) or {}
    order_type_options = settings.get(SettingCategory.order_type.value, ORDER_TYPE_OPTIONS)
    
    bank_account_options = settings.get(SettingCategory.bank_account.value, [])
    payment_method_options = settings.get(SettingCategory.payment_method.value, [])

    detail = {
        "employee_names": list(employee_names),
        "profile_names": list(profile_names),
        "we_chats": list(we_chats),
            "whatsapp_numbers": list(whatsapp_numbers),
        "order_type_options": order_type_options,
        "bank_account_options": bank_account_options,
        "payment_method_options": payment_method_options
    }

    paginated_data, pagination_meta, filter_opts = _filter_and_paginate(dashboard_data)

    return {
        "status_code": 200,
        "status": "success",
        "message": "Dashboard data fetched successfully",
        "data": paginated_data,
        "pagination": pagination_meta,
        "detail": _build_dashboard_detail(filter_opts)
    }

@router.patch("/dashboard/orders/{order_db_id}", response_model=ApiResponse[dict])
def update_dashboard_order(order_db_id: str, update_data: DashboardUpdate, current_user: dict = Depends(get_current_user)):
    """
    Unified update endpoint for the dashboard using Order Database ID (Hex).
    Updates relevant collections based on provided fields.
    """
    # 1. Map fields to collections
    update_dict = update_data.model_dump(exclude_unset=True)
    if not update_dict:
        return {
            "status_code": 200,
            "status": "success",
            "message": "No changes provided",
            "data": None
        }

    # 2. Map fields to collections
    # CLIENT fields — all whatsapp variants here go to clients_collection.whatsapp_no
    client_fields = ["client_name", "client_id", "client_country", "client_Email",
                     "client_whatsapp_number", "client_whatsapp_no", "whatsapp_no",
                     "client_link", "bank_account", "client_affiliations", "client_handler"]
    # ORDER fields — profile_whatsapp_number goes to orders_collection.whatsapp_number
    # NOTE: plain 'whatsapp_number' is NOT in client_fields, so it will ONLY update the order
    order_fields = ["order_id", "manuscript_id", "order_date", "reference_id", "ref_no", "journal_name",
                    "title", "order_type", "we_chat", "whatsapp_number", "profile_whatsapp_number",
                    "profile_name", "index", "rank", "currency", "total_amount", "writing_amount",
                    "modification_amount", "implementation_amount", "po_amount",
                    "writing_start_date", "writing_end_date", "modification_start_date",
                    "modification_end_date", "po_start_date", "po_end_date", 
                    "implementation_start_date", "implementation_end_date", "payment_status",
                    "remarks", "order_status", "payment_drive_link", "receipt_drive_link",
                    "receive_bank_account", "paid_amount", "clients_details", "client_details",
                    "client_drive_link", "is_new_order"]

    # Map client_handler_name to client_handler email if provided
    if "client_handler_name" in update_dict:
        email = get_user_email_by_name(update_dict["client_handler_name"])
        update_dict["client_handler"] = email
        update_dict.pop("client_handler_name", None)
    payment_fields = ["phase_1_payment", "phase_1_payment_date", "phase_1_payment_details", "phase_1_receive_bank_account", "phase_1_payment_method", "phase_2_payment", "phase_2_payment_date", "phase_2_payment_details", "phase_2_receive_bank_account", "phase_2_payment_method", "phase_3_payment", "phase_3_payment_date", "phase_3_payment_details", "phase_3_receive_bank_account", "phase_3_payment_method", "payment_status", "paid_amount"]

    # Get the order to verify it exists and find linked client
    try:
        order = orders_collection.find_one({"_id": ObjectId(order_db_id)})
    except Exception:
         raise HTTPException(status_code=400, detail="Invalid order_db_id format")
         
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    old_client_id = order["client_id"]
    order_custom_id = order["order_id"]
    client_doc = clients_collection.find_one({"client_id": old_client_id})
    payment_doc = payments_collection.find_one({"order_id": order_custom_id})

    # 3. Perform Updates
    
    # Update Clients & Handle client_id change
    client_updates = {f: update_dict[f] for f in client_fields if f in update_dict}
    if client_updates:
        # Check if client_id itself is changing
        new_client_id = client_updates.get("client_id")
        
        # Map dashboard field names back to client collection names
        mapped_client_updates = {}
        # All three whatsapp variants from the client form map to whatsapp_no in the clients collection
        client_field_mapping = {
            "client_name": "name",
            "client_id": "client_id",
            "client_country": "country",
            "client_Email": "email",
            "client_whatsapp_number": "whatsapp_no",   # frontend key → DB key
            "client_whatsapp_no": "whatsapp_no",       # alternate frontend key
            "whatsapp_no": "whatsapp_no",              # direct key
            "client_link": "client_link",
            "bank_account": "bank_account",
            "client_affiliations": "affiliation"
        }
        for k, v in client_updates.items():
            db_key = client_field_mapping.get(k, k)
            mapped_client_updates[db_key] = v

        # Update the client record
        clients_collection.update_one({"client_id": old_client_id}, {"$set": mapped_client_updates})
        if client_doc:
            record_audit_log(old_client_id, "clients", client_doc, mapped_client_updates, current_user["email"])

        # If client_id changed, ripple to all related collections
        if new_client_id and new_client_id != old_client_id:
            orders_collection.update_many({"client_id": old_client_id}, {"$set": {"client_id": new_client_id}})
            payments_collection.update_many({"client_id": old_client_id}, {"$set": {"client_id": new_client_id}})
            manuscripts_collection.update_many({"client_id": old_client_id}, {"$set": {"client_id": new_client_id}})
            
            # Ripple to audit logs so history isn't lost for the client
            audit_logs_collection.update_many({"document_id": old_client_id, "collection_name": "clients"}, {"$set": {"document_id": new_client_id}})
            
            # Update local variable for subsequent order updates in this same request
            old_client_id = new_client_id

    # Update Orders
    order_updates = {f: update_dict[f] for f in order_fields if f in update_dict}
    if order_updates:
        # Map dashboard field names back to order collection field names
        # IMPORTANT: profile_whatsapp_number (frontend) → whatsapp_number (orders DB)
        #            This is kept COMPLETELY separate from client's whatsapp_no field.
        mapped_order_updates = {}
        order_field_mapping = {
            "ref_no": "client_ref_no",
            "client_details": "clients_details",
            "profile_whatsapp_number": "whatsapp_number",  # Profile WA → orders.whatsapp_number
        }

        for k, v in order_updates.items():
            db_key = order_field_mapping.get(k, k)
            mapped_order_updates[db_key] = v

        new_order_id = mapped_order_updates.get("order_id")
        if new_order_id and new_order_id != order.get("order_id"):
            if orders_collection.find_one({"order_id": new_order_id}):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Order ID '{new_order_id}' already exists")

        new_reference_id = mapped_order_updates.get("reference_id")
        if new_reference_id and new_reference_id != order.get("reference_id"):
            if orders_collection.find_one({"reference_id": new_reference_id}):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Reference ID '{new_reference_id}' already exists")

        mapped_order_updates["updated_at"] = datetime.utcnow()
        orders_collection.update_one({"_id": ObjectId(order_db_id)}, {"$set": mapped_order_updates})
        record_audit_log(str(order_db_id), "orders", order, mapped_order_updates, current_user["email"])

    # Update Payments â€” direct field update (same pattern as orders/clients)
    payment_updates_raw = {f: update_dict[f] for f in payment_fields if f in update_dict}
    if payment_updates_raw:
        payments_collection.update_one(
            {"order_id": order_custom_id},
            {"$set": payment_updates_raw},
            upsert=True
        )
        if payment_doc:
            record_audit_log(str(order_db_id), "payments", payment_doc, payment_updates_raw, current_user["email"])
        
    # Sync with payment_history_collection if order, client, or payment fields were updated
    if client_updates or order_updates or payment_updates_raw:
        latest_order = orders_collection.find_one({"order_id": order_custom_id})
        if latest_order:
            latest_client = clients_collection.find_one({"client_id": latest_order["client_id"]})
            latest_payment = payments_collection.find_one({"order_id": order_custom_id})
            
            client_name = latest_client.get("name") if latest_client else "Unknown Client"
            
            history_record = {
                "client_name": client_name,
                "client_id": latest_order["client_id"],
                "order_id": order_custom_id,
                "reference_id": latest_order.get("reference_id"),
                "order_title": latest_order.get("title") or "Unknown Title",
                "amount": latest_order.get("total_amount", 0.0),
                "paid_amount": latest_payment.get("paid_amount", 0.0) if latest_payment else 0.0,
                "payment_date": latest_payment.get("payment_date") if latest_payment else None,
                "payment_received_account": latest_payment.get("payment_received_account") if latest_payment else None,
                "phase_1_payment": latest_payment.get("phase_1_payment", 0.0) if latest_payment else 0.0,
                "phase_1_payment_date": latest_payment.get("phase_1_payment_date") if latest_payment else None,
                "phase_1_payment_details": latest_payment.get("phase_1_payment_details") if latest_payment else None,
                "phase_1_receive_bank_account": latest_payment.get("phase_1_receive_bank_account") if latest_payment else None,
                "phase_2_payment": latest_payment.get("phase_2_payment", 0.0) if latest_payment else 0.0,
                "phase_2_payment_date": latest_payment.get("phase_2_payment_date") if latest_payment else None,
                "phase_2_payment_details": latest_payment.get("phase_2_payment_details") if latest_payment else None,
                "phase_2_receive_bank_account": latest_payment.get("phase_2_receive_bank_account") if latest_payment else None,
                "phase_3_payment": latest_payment.get("phase_3_payment", 0.0) if latest_payment else 0.0,
                "phase_3_payment_date": latest_payment.get("phase_3_payment_date") if latest_payment else None,
                "phase_3_payment_details": latest_payment.get("phase_3_payment_details") if latest_payment else None,
                "phase_3_receive_bank_account": latest_payment.get("phase_3_receive_bank_account") if latest_payment else None,
                "phase_1_payment_method": latest_payment.get("phase_1_payment_method") if latest_payment else None,
                "phase_2_payment_method": latest_payment.get("phase_2_payment_method") if latest_payment else None,
                "phase_3_payment_method": latest_payment.get("phase_3_payment_method") if latest_payment else None,
                "updated_at": datetime.utcnow()
            }
            
            payment_history_collection.update_one(
                {"order_id": order_custom_id},
                {
                    "$set": history_record,
                    "$setOnInsert": {"created_at": datetime.utcnow()}
                },
                upsert=True
            )



    invalidate_dashboard_cache()

    return {
        "status_code": 200,
        "status": "success",
        "message": "Dashboard order updated successfully",
        "data": None
    }

# --- UNIFIED CREATE API ---

@router.post("/unified/create", response_model=ApiResponse[dict], status_code=status.HTTP_201_CREATED)
def create_unified_record(
    request: Annotated[Json[UnifiedCreateRequest], Form()],
    client_photo: Optional[UploadFile] = File(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Unified API to create client, order, manuscript, and payment records in one request.
    Accessible to all roles (Employee, Manager, Admin).

    Features:
    - Creates client if doesn't exist, updates if exists
    - Always creates order with unique reference_id
    - Optionally creates manuscript linked to client and order
    - Optionally creates payment record
    - payment_drive_link flows from client to order automatically
    """

    # Step 1: Handle Client ID and Reference ID Auto-generation
    if not request.client_id and not clients_collection.find_one({"name": request.client_name}):
        request.client_id = generate_custom_id("CL", clients_collection, current_user)
    
    if not request.reference_id:
        request.reference_id = generate_custom_id("REF", orders_collection, current_user)

    # Step 1: Handle Client Creation/Update
    existing_client = clients_collection.find_one({"client_id": request.client_id}) if request.client_id else clients_collection.find_one({"name": request.client_name})


    if not existing_client:
        # Create new client
        client_data = {
            "client_id": request.client_id,
            "name": request.client_name,
            "country": request.client_country,
            "email": request.client_email,
            "whatsapp_no": request.client_whatsapp_no,
            "client_ref_no": request.client_ref_no,
            "client_link": request.client_link,
            "bank_account": request.client_bank_account,
            "affiliation": request.client_affiliation,
            "payment_drive_link": request.payment_drive_link,
            "client_drive_link": request.client_drive_link,
            "total_orders": 0,
            "client_handler": current_user.get("email") if current_user["role"] == UserRole.EMPLOYEE else get_user_email_by_name(request.client_handler),
            "created_at": datetime.utcnow(),
            "has_photo": False
        }

        # Process photo file if provided via form
        if client_photo and client_photo.filename:
            try:
                content = client_photo.file.read()
                mime = client_photo.content_type or "image/png"
                photo_path = save_bytes_to_file(content, mime, "clients")
                client_data["photo_path"] = photo_path
                client_data["photo_mime"] = mime
                client_data["has_photo"] = True
            except Exception as e:
                print(f"Error saving client photo from upload: {e}")
        # Fallback to base64 if provided
        elif request.client_photo_base64:
            try:
                import base64
                photo_b64 = request.client_photo_base64
                if "," in photo_b64:
                    photo_b64 = photo_b64.split(",")[1]
                content = base64.b64decode(photo_b64)
                mime = request.client_photo_mime or "image/png"
                photo_path = save_bytes_to_file(content, mime, "clients")
                client_data["photo_path"] = photo_path
                client_data["photo_mime"] = mime
                client_data["has_photo"] = True
            except Exception as e:
                print(f"Error decoding client photo: {e}")

        clients_collection.insert_one(client_data)
        client_id = request.client_id
        client_payment_drive_link = request.payment_drive_link
    else:
        # Use existing client, do not update fields
        client_id = existing_client["client_id"]
        
        # Get the current payment_drive_link from existing client
        client_payment_drive_link = existing_client.get("payment_drive_link")

    # Step 2: Create Manuscript (Optional)
    manuscript_id = None
    if request.create_manuscript and request.manuscript_title:
        manuscript_data = {
            "manuscript_id": f"MS-{client_id}-{request.reference_id}",
            "title": request.manuscript_title,
            "journal_name": request.manuscript_journal_name or request.journal_name,
            "order_type": request.order_type,
            "client_id": client_id,
            "created_at": datetime.utcnow()
        }
        manuscripts_collection.insert_one(manuscript_data)
        manuscript_id = manuscript_data["manuscript_id"]

    # Step 3: Create Order
    # Generate unique order_id
    global_order_count = orders_collection.count_documents({}) + 1
    order_id = f"ORD-{datetime.utcnow().strftime('%Y')}-{global_order_count:03d}"
    
    # Ensure uniqueness in case of deleted documents mapping to same count
    while orders_collection.find_one({"order_id": order_id}):
        global_order_count += 1
        order_id = f"ORD-{datetime.utcnow().strftime('%Y')}-{global_order_count:03d}"

    # Ensure reference_id is unique
    if orders_collection.find_one({"reference_id": request.reference_id}):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Reference ID '{request.reference_id}' already exists"
        )

    # Auto-update is_new_order based on existing orders
    existing_orders_count = orders_collection.count_documents({"client_id": client_id})
    if existing_orders_count > 0:
        is_new_order_val = "no"
        orders_collection.update_many({"client_id": client_id}, {"$set": {"is_new_order": "no"}})
    else:
        is_new_order_val = "yes"

    order_data = {
        "order_id": order_id,
        "reference_id": request.reference_id,
        "profile_name": request.profile_name,
        "we_chat": request.we_chat,
        "client_ref_no": request.client_ref_no,
        "s_no": global_order_count,
        "order_date": parse_date(request.order_date),
        "client_id": client_id,
        "manuscript_id": manuscript_id,
        "journal_name": request.journal_name,
        "title": request.title,
        "order_type": request.order_type,
        "index": request.index,
        "rank": request.rank,
        "currency": request.currency or "USD",
        "total_amount": request.total_amount or 0,
        "writing_amount": request.writing_amount or 0,
        "modification_amount": request.modification_amount or 0,
        "implementation_amount": request.implementation_amount or 0,
        "po_amount": request.po_amount or 0,
        "writing_start_date": parse_date(request.writing_start_date) or parse_date(request.write_start_date),
        "writing_end_date": parse_date(request.writing_end_date),
        "modification_start_date": parse_date(request.modification_start_date),
        "modification_end_date": parse_date(request.modification_end_date),
        "po_start_date": parse_date(request.po_start_date),
        "po_end_date": parse_date(request.po_end_date),
        "payment_status": request.payment_status or "Pending",
        "order_status": "Active",
        "payment_drive_link": request.payment_drive_link or client_payment_drive_link,
        "clients_details": request.clients_details or getattr(request, 'client_details', None),
        "client_drive_link": request.client_drive_link,
        "receive_bank_account": request.receive_bank_account,
        "is_new_order": is_new_order_val,
        "remarks": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    orders_collection.insert_one(order_data)

    # Step 4: Create Payment (Optional)
    payment_created = False
    if request.create_payment and request.payment_amount:
        payment_data = {
            "client_ref_number": request.client_ref_no,
            "reference_id": request.reference_id,
            "client_id": client_id,
            "order_id": order_id,
            "phase": request.payment_phase or 1,
            "amount": request.payment_amount,
            "payment_received_account": request.payment_received_account,
            "payment_date": parse_date(request.payment_date) or datetime.utcnow(),
            "status": "paid",
            "paid_amount": request.payment_amount,
            "created_at": datetime.utcnow()
        }

        # Update phase-specific fields
        phase = payment_data["phase"]
        payment_data[f"phase_{phase}_payment"] = request.payment_amount
        payment_data[f"phase_{phase}_payment_date"] = payment_data["payment_date"]

        payments_collection.insert_one(payment_data)

        # Sync with payment_history_collection
        history_item = {
            "client_name": request.client_name,
            "client_id": client_id,
            "order_id": order_id,
            "reference_id": request.reference_id,
            "amount": request.total_amount or request.payment_amount,
            "paid_amount": request.payment_amount,
            "payment_date": payment_data["payment_date"],
            "payment_received_account": request.payment_received_account,
            "order_title": request.title or "Unknown Title",
            "phase_1_payment": payment_data.get("phase_1_payment", 0.0),
            "phase_1_payment_date": payment_data.get("phase_1_payment_date"),
            "phase_1_payment_details": payment_data.get("phase_1_payment_details"),
            "phase_2_payment": payment_data.get("phase_2_payment", 0.0),
            "phase_2_payment_date": payment_data.get("phase_2_payment_date"),
            "phase_2_payment_details": payment_data.get("phase_2_payment_details"),
            "phase_3_payment": payment_data.get("phase_3_payment", 0.0),
            "phase_3_payment_date": payment_data.get("phase_3_payment_date"),
            "phase_3_payment_details": payment_data.get("phase_3_payment_details"),
            "phase_1_receive_bank_account": payment_data.get("phase_1_receive_bank_account"),
            "phase_1_payment_method": payment_data.get("phase_1_payment_method"),
            "phase_2_receive_bank_account": payment_data.get("phase_2_receive_bank_account"),
            "phase_2_payment_method": payment_data.get("phase_2_payment_method"),
            "phase_3_receive_bank_account": payment_data.get("phase_3_receive_bank_account"),
            "phase_3_payment_method": payment_data.get("phase_3_payment_method"),
            "created_at": datetime.utcnow()
        }
        payment_history_collection.insert_one(history_item)

        # Update order total_amount only if it wasn't already set from request
        if not order_data.get("total_amount"):
            orders_collection.update_one(
                {"order_id": order_id},
                {"$set": {"total_amount": request.payment_amount}}
            )
        payment_created = True

    # Step 5: Update Client Order Count
    clients_collection.update_one(
        {"client_id": client_id},
        {"$inc": {"total_orders": 1}}
    )
    invalidate_dashboard_cache()


    # Return comprehensive response
    return {
        "status_code": 201,
        "status": "success",
        "message": "Unified record created successfully",
        "data": {
            "client_id": client_id,
            "order_id": order_id,
            "reference_id": request.reference_id,
            "manuscript_id": manuscript_id,
            "payment_created": payment_created,
            "client_created": existing_client is None,
            "created_records": {
                "client": existing_client is None,
                "order": True,
                "manuscript": request.create_manuscript,
                "payment": payment_created
            },
            "payment_drive_link_used": client_payment_drive_link
        }
    }

# --- AUDIT LOGS API ---

@router.get("/history/{collection_name}/{document_id}/{field_name}", response_model=ApiResponse[list[dict]])
def get_field_history(collection_name: str, document_id: str, field_name: str, current_user: dict = Depends(get_current_user)):
    """
    Fetch the edit history for a specific field of a specific document.
    """
    logs = list(audit_logs_collection.find({
        "collection_name": collection_name,
        "document_id": document_id,
        "field_name": field_name
    }).sort("edited_at", -1))
    
    # Format for response
    formatted_logs = []
    for log in logs:
        formatted_logs.append({
            "old_value": log.get("old_value"),
            "new_value": log.get("new_value"),
            "edited_by": log.get("edited_by"),
            "edited_at": log.get("edited_at")
        })

    return {
        "status_code": 200,
        "status": "success",
        "message": "History fetched successfully",
        "data": formatted_logs
    }
