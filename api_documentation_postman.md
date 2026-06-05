# Full API Documentation (with Postman Examples)

Base URL: `http://localhost:8000` (or your configured backend URL)

All endpoints (except login/initialization) require a valid JWT Bearer token in the `Authorization` header.
`Authorization: Bearer <your_access_token>`

---

## GET /
**Endpoint:** `GET /`
**Name:** read_root
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /currency/exchange-rate
**Endpoint:** `GET /currency/exchange-rate`
**Name:** get_exchange_rate
**Description:** Get current INR to USD exchange rate with caching.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /currency/inr-to-usd
**Endpoint:** `POST /currency/inr-to-usd`
**Name:** convert_inr_to_usd_endpoint
**Description:** Convert amount from INR to USD.
Request: {"amount_inr": 1000}
Response includes current rate and converted amount.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /currency/usd-to-inr
**Endpoint:** `POST /currency/usd-to-inr`
**Name:** convert_usd_to_inr_endpoint
**Description:** Convert amount from USD to INR.
Request: {"amount_usd": 15}
Response includes current rate and converted amount.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /currency/convert
**Endpoint:** `POST /currency/convert`
**Name:** convert_currency_endpoint
**Description:** Convert amount between any supported currencies (USD, INR, CNY, AED, SAR).
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /init-super-admin
**Endpoint:** `POST /init-super-admin`
**Name:** init_super_admin
**Description:** Endpoint to initialize the first super admin users. 
Works if fewer than 5 admins exist in the database.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /login
**Endpoint:** `POST /login`
**Name:** login
**Description:** Shared login endpoint. Admins and Managers require OTP.
Employees login directly.
**Headers:**
- `Content-Type: application/json`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /verify-otp
**Endpoint:** `POST /verify-otp`
**Name:** verify_otp
**Description:** Verify OTP for Admin/Manager login.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /logout
**Endpoint:** `POST /logout`
**Name:** logout
**Description:** Logout the current user by invalidating their token.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /otp-status
**Endpoint:** `GET /otp-status`
**Name:** get_otp_status
**Description:** Get the current status of OTP verification (enabled/disabled).
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /toggle-otp
**Endpoint:** `POST /toggle-otp`
**Name:** toggle_otp
**Description:** Enable or disable OTP verification globally.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /users
**Endpoint:** `POST /users`
**Name:** create_user
**Description:** Create a new User (Admin, Manager, or Employee).
Restricted to Super Admin and Manager. 
One additional Admin is allowed (total 2).
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /managers
**Endpoint:** `POST /managers`
**Name:** create_manager
**Description:** Create a new Manager.
Restricted to Admin and Manager only.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## PUT /users/me/password
**Endpoint:** `PUT /users/me/password`
**Name:** update_own_password
**Description:** Update own password. Available to all roles.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## PUT /users/password
**Endpoint:** `PUT /users/password`
**Name:** update_user_password
**Description:** Update a User's password. Restricted to Admin and Super Admin.
Admins can only change USER role passwords.
Super Admins can change ADMIN and USER role passwords.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /users
**Endpoint:** `GET /users`
**Name:** get_all_users
**Description:** Get all regular Users. Accessible to Admin and Super Admin.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /admins
**Endpoint:** `GET /admins`
**Name:** get_all_admins
**Description:** Get all Admins and Super Admins. Accessible to Super Admin only.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## PUT /users/permissions
**Endpoint:** `PUT /users/permissions`
**Name:** update_user_permissions
**Description:** Update an Employee's column-level permissions. 
Restricted to Admin and Manager.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## PUT /users/{email}/profile
**Endpoint:** `PUT /users/{email}/profile`
**Name:** update_user_profile
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## PUT /users/profile
**Endpoint:** `PUT /users/profile`
**Name:** update_user_profile
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /users/{email}/photo
**Endpoint:** `GET /users/{email}/photo`
**Name:** get_user_photo
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /users/{email}/photo
**Endpoint:** `POST /users/{email}/photo`
**Name:** upload_user_photo
**Description:** Upload or update a user's profile photo.
The authenticated user can update their own photo.
Admin and Manager can update any user's photo.
Saves file to static/uploads/users/ and stores the path in MongoDB.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## DELETE /users/{email}/photo
**Endpoint:** `DELETE /users/{email}/photo`
**Name:** delete_user_photo
**Description:** Delete a user's profile photo.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /clients/{client_id}/photo
**Endpoint:** `POST /clients/{client_id}/photo`
**Name:** upload_client_photo
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## DELETE /clients/{client_id}/photo
**Endpoint:** `DELETE /clients/{client_id}/photo`
**Name:** delete_client_photo
**Description:** Delete a client's profile photo.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /clients/{client_id}/photo
**Endpoint:** `GET /clients/{client_id}/photo`
**Name:** get_client_photo
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /orders/{order_db_id}/receipt/{phase}
**Endpoint:** `POST /orders/{order_db_id}/receipt/{phase}`
**Name:** upload_receipt_screenshot
**Description:** Upload a payment receipt screenshot/document for an order phase (1, 2, or 3).
- Accepts images (png, jpg, etc.), PDFs, and Word docs
- Enforces 10 MB size limit
- Saves file to static/uploads/receipts/ and stores path in orders collection
- Clears dashboard cache after successful upload
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /orders/{order_db_id}/receipt/{phase}
**Endpoint:** `GET /orders/{order_db_id}/receipt/{phase}`
**Name:** get_receipt_screenshot
**Description:** Download/serve a payment receipt screenshot for an order phase.
Returns the image file from disk, or 404 if not found.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## DELETE /orders/{order_db_id}/receipt/{phase}
**Endpoint:** `DELETE /orders/{order_db_id}/receipt/{phase}`
**Name:** delete_receipt_screenshot
**Description:** Delete a payment receipt screenshot from an order phase.
Removes the file from disk and unsets the path field in MongoDB.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /users/profiles/append
**Endpoint:** `POST /users/profiles/append`
**Name:** append_profile_name
**Description:** Append a new profile name to a user's list.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /users/we_chats/append
**Endpoint:** `POST /users/we_chats/append`
**Name:** append_we_chat
**Description:** Append a new WeChat account to a user's list.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /users/whatsapp_numbers/append
**Endpoint:** `POST /users/whatsapp_numbers/append`
**Name:** append_whatsapp_number
**Description:** Append a new WhatsApp number to a user's list.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## DELETE /users/whatsapp_numbers/{email}/{whatsapp_number}
**Endpoint:** `DELETE /users/whatsapp_numbers/{email}/{whatsapp_number}`
**Name:** delete_whatsapp_number
**Description:** Remove a WhatsApp number from a user's list.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## DELETE /users/we_chats/{email}/{we_chat}
**Endpoint:** `DELETE /users/we_chats/{email}/{we_chat}`
**Name:** delete_we_chat
**Description:** Remove a WeChat account from a user's list.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## DELETE /users/profiles/{email}/{profile_name}
**Endpoint:** `DELETE /users/profiles/{email}/{profile_name}`
**Name:** delete_profile_name
**Description:** Remove a profile name from a user's list.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /users/me/details
**Endpoint:** `GET /users/me/details`
**Name:** get_own_details
**Description:** Get current user profile details including country stats and order statuses.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /users/{email}/details
**Endpoint:** `GET /users/{email}/details`
**Name:** get_user_details
**Description:** Get profile details of any user including country stats and order statuses.
Restricted to Admin and Manager.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /clients
**Endpoint:** `POST /clients`
**Name:** create_client
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /users/options
**Endpoint:** `GET /users/options`
**Name:** get_user_options
**Description:** Returns profile_names, whatsapp_numbers, and we_chats as flat lists
for use as dropdown options in the frontend.
- Admin/Manager: aggregates across ALL users.
- Employee: returns only their own assigned values.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /clients
**Endpoint:** `GET /clients`
**Name:** get_clients
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /clients/{client_id}
**Endpoint:** `GET /clients/{client_id}`
**Name:** get_client
**Description:** Fetch full client profile including:
- All client fields
- Full order list with payment phase details
- Client photo embedded as base64 (photo_base64 + photo_mime)
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## DELETE /clients/{client_id}
**Endpoint:** `DELETE /clients/{client_id}`
**Name:** delete_client
**Description:** Delete a client and cascade delete all their orders, payments, and manuscripts.
Restricted to Admin and Manager.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /clients/bulk-delete
**Endpoint:** `POST /clients/bulk-delete`
**Name:** bulk_delete_clients
**Description:** Bulk delete clients and cascade delete all their orders, payments, and manuscripts.
Restricted to Admin and Manager.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /clients/assign
**Endpoint:** `POST /clients/assign`
**Name:** assign_client
**Description:** Assign an Employee to a Client.
Restricted to Admin and Manager.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /manuscripts
**Endpoint:** `POST /manuscripts`
**Name:** create_manuscript
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /manuscripts
**Endpoint:** `GET /manuscripts`
**Name:** get_manuscripts
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /orders
**Endpoint:** `POST /orders`
**Name:** create_order
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /orders
**Endpoint:** `GET /orders`
**Name:** get_orders
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /payments
**Endpoint:** `POST /payments`
**Name:** create_payment
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /payments
**Endpoint:** `GET /payments`
**Name:** get_payments
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /payments/history
**Endpoint:** `GET /payments/history`
**Name:** get_payment_history
**Description:** Detailed payment history from the flattened payment_history_collection.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /payments/pending-summary
**Endpoint:** `GET /payments/pending-summary`
**Name:** get_pending_payment_summary
**Description:** Summary of pending payments across all clients and orders.
Restricted to Manager and Admin.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /settings
**Endpoint:** `GET /settings`
**Name:** get_all_settings
**Description:** Fetch all settings grouped in a single document.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /settings/{category}
**Endpoint:** `GET /settings/{category}`
**Name:** get_setting_category
**Description:** Fetch options for a specific setting category.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /settings/{category}/add
**Endpoint:** `POST /settings/{category}/add`
**Name:** add_setting_option
**Description:** Add a new option to a setting category.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## DELETE /settings/{category}/remove
**Endpoint:** `DELETE /settings/{category}/remove`
**Name:** remove_setting_option
**Description:** Remove an option from a setting category.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## PUT /settings/{category}/update
**Endpoint:** `PUT /settings/{category}/update`
**Name:** update_setting_option
**Description:** Update an existing option in a setting category.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /bank-accounts
**Endpoint:** `GET /bank-accounts`
**Name:** get_bank_accounts
**Description:** Get all bank accounts.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## POST /bank-accounts
**Endpoint:** `POST /bank-accounts`
**Name:** create_bank_account
**Description:** Create a new bank account.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## PUT /bank-accounts/{account_id}
**Endpoint:** `PUT /bank-accounts/{account_id}`
**Name:** update_bank_account
**Description:** Update a bank account.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## DELETE /bank-accounts/{account_id}
**Endpoint:** `DELETE /bank-accounts/{account_id}`
**Name:** delete_bank_account
**Description:** Delete a bank account.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## GET /dashboard/orders
**Endpoint:** `GET /dashboard/orders`
**Name:** get_dashboard_orders
**Description:** Unified endpoint for the frontend dashboard.
Optimized with MongoDB Aggregation Pipeline ($lookup + $unwind).
Shows clients even if no orders exist.
Includes caching for improved performance.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

## PATCH /dashboard/orders/{order_db_id}
**Endpoint:** `PATCH /dashboard/orders/{order_db_id}`
**Name:** update_dashboard_order
**Description:** Unified update endpoint for the dashboard using Order Database ID (Hex).
Updates relevant collections based on provided fields.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## POST /unified/create
**Endpoint:** `POST /unified/create`
**Name:** create_unified_record
**Description:** Unified API to create client, order, manuscript, and payment records in one request.
Accessible to all roles (Employee, Manager, Admin).

Features:
- Creates client if doesn't exist, updates if exists
- Always creates order with unique reference_id
- Optionally creates manuscript linked to client and order
- Optionally creates payment record
- payment_drive_link flows from client to order automatically
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

**Body (raw JSON example):**
```json
{
  // See OpenAPI spec for exact fields
}
```

---

## GET /history/{collection_name}/{document_id}/{field_name}
**Endpoint:** `GET /history/{collection_name}/{document_id}/{field_name}`
**Name:** get_field_history
**Description:** Fetch the edit history for a specific field of a specific document.
**Headers:**
- `Content-Type: application/json`
- `Authorization: Bearer <token>`

---

