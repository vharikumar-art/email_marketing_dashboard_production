# WhatsApp Numbers Feature - Visual Overview

## Feature Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    User Dashboard Request                       │
│                  GET /dashboard/orders                          │
│                                                                 │
│  Header: Authorization: Bearer <token>                          │
│  Query: role=admin/manager/employee                             │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│              FastAPI Route Handler                              │
│         get_dashboard_orders(current_user)                      │
│                                                                 │
│  1. Check cache (by user role + email)                          │
│  2. Run aggregation pipeline (clients → orders → payments)      │
│  3. Enrich with WhatsApp numbers ← NEW STEP                     │
│  4. Build detail section (dropdown options)                     │
│  5. Return response                                             │
└─────────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────┴───────────────────┐
        │                                       │
        ▼                                       ▼
   ┌─────────────────────┐         ┌──────────────────────┐
   │  Dashboard Data     │         │  Detail (Dropdowns)  │
   │  (Each Order)       │         │                      │
   │                     │         │  - employee_names    │
   │ - order_id          │         │  - profile_names     │
   │ - profile_name      │         │  - we_chats          │
   │ - we_chat           │         │  - whatsapp_numbers  │
   │ - whatsapp_number   │         │  - order_type_opts   │
   │ - profile_whatsapp  │         │  - bank_accounts     │
   │   _number ← NEW     │         │  - payment_methods   │
   │ - client_handler    │         │                      │
   │ - ... other fields  │         └──────────────────────┘
   │                     │
   └─────────────────────┘
```

---

## Data Flow Diagram

```
Users Collection (MongoDB)
┌──────────────────────────────────────┐
│ User: MUTHU                          │
│ email: muthu@company.com             │
│ role: employee                       │
│ whatsapp_numbers: [                  │
│   "+91-9876543210",                  │
│   "+91-9876543211",                  │
│   "+91-9876543212"                   │
│ ]                                    │
└────────────────────┬─────────────────┘
                     │
                     │ User lookup
                     │ by email/name
                     │
        ┌────────────┴────────────┐
        │                         │
        ▼                         ▼
   ADMIN Sees              EMPLOYEE Sees
   ┌──────────────┐        ┌──────────────┐
   │ ALL employees│        │ Only if:     │
   │ WhatsApp #s  │        │ current_user │
   │              │        │ .email ==    │
   │ MUTHU:       │        │ handler_email│
   │ ["+91-9876..│        │              │
   │   "+91-9876..│        │ MUTHU:       │
   │   "+91-9876..│        │ ["+91-9876..│
   │              │        │              │
   │ RAJINI:      │        │ RAJINI:      │
   │ ["+91-1111..│        │ [] (empty)   │
   │   "+91-2222..│        │              │
   │              │        └──────────────┘
   └──────────────┘
```

---

## API Response Structure

### Request
```
GET /dashboard/orders
Headers: {
  Authorization: Bearer eyJhbGc...
}
```

### Response (Admin/Manager View)
```json
{
  "status_code": 200,
  "status": "success",
  "message": "Dashboard data fetched successfully",
  
  "data": [
    {
      "order_id": "ORD-2024-001",
      "order_db_id": "507f1f77bcf86cd799439011",
      "s_no": 1,
      "client_id": "CL-001",
      "client_name": "ABC Research Ltd",
      "profile_name": "MUTHU",
      
      "profile_whatsapp_number": [
        "+91-9876543210",
        "+91-9876543211",
        "+91-9876543212"
      ],
      
      "whatsapp_number": "+91-9876543210",  // Current/assigned number
      "we_chat": "muthu_chat_123",
      "client_handler": "muthu@company.com",
      
      "order_type": "WO",
      "order_date": "2024-06-01T10:00:00",
      "total_amount": 5000.00,
      "payment_status": "Pending",
      
      ...other fields...
    },
    {
      "order_id": "ORD-2024-002",
      "profile_name": "RAJINI",
      
      "profile_whatsapp_number": [
        "+91-1111111111",
        "+91-2222222222"
      ],
      
      ...
    }
  ],
  
  "detail": {
    "employee_names": ["MUTHU", "RAJINI", "VJ", "AK"],
    "profile_names": ["MUTHU", "RAJINI", "VJ", "AK", "SUB_PROFILES"],
    "we_chats": ["muthu_chat", "rajini_chat", "vj_chat"],
    "whatsapp_numbers": [        // All available numbers
      "+91-9876543210",
      "+91-9876543211",
      "+91-1111111111",
      "+91-2222222222"
    ],
    "order_type_options": [
      "WO / PO",
      "MO / PO",
      "WO",
      ...
    ],
    "bank_account_options": [...],
    "payment_method_options": [...]
  }
}
```

### Response (Employee View - Own Order)
```json
{
  "data": [
    {
      "order_id": "ORD-2024-001",
      "profile_name": "MUTHU",
      
      "profile_whatsapp_number": [
        "+91-9876543210",
        "+91-9876543211",
        "+91-9876543212"
      ],
      
      ...  // Same order MUTHU created
    }
  ],
  "detail": {
    "employee_names": ["MUTHU"],  // Only themselves
    "profile_names": ["MUTHU"],
    "we_chats": ["muthu_chat"],
    "whatsapp_numbers": [
      "+91-9876543210",
      "+91-9876543211",
      "+91-9876543212"
    ],
    ...
  }
}
```

### Response (Employee View - Other's Order)
```json
{
  "data": [
    {
      "order_id": "ORD-2024-002",
      "profile_name": "RAJINI",
      
      "profile_whatsapp_number": [],  // ← EMPTY (no access)
      
      ...  // Order created by RAJINI
    }
  ],
  "detail": {
    "employee_names": [],  // Can't see others
    "profile_names": ["MUTHU"],  // Only their own profiles
    "we_chats": ["muthu_chat"],
    "whatsapp_numbers": ["+91-9876543210", ...],  // Only their own
    ...
  }
}
```

---

## Role-Based Access Control Visualization

```
          User Makes Request
                 │
                 ▼
         ┌───────────────────┐
         │   Check Role      │
         └───────┬───────────┘
          ┌──────┼──────┐
          │      │      │
          ▼      ▼      ▼
       ADMIN  MANAGER  EMPLOYEE
        │       │        │
        │       │        │
    Query all Query all Query self only
    employees employees └─────┬─────┐
        │       │            │     │
        │       │      ┌──────┘     │
        │       │      │            │
        ▼       ▼      ▼            ▼
   ┌─────────────────────┐    ┌────────────┐
   │ Get ALL employee    │    │ Get current│
   │ whatsapp_numbers    │    │ user's own │
   │ from users table    │    │ whatsapp#s │
   │                     │    │            │
   │ Result: Complete    │    │ Result:    │
   │ list for ALL        │    │ Only their │
   │ employees           │    │ numbers    │
   └────────┬────────────┘    └─────┬──────┘
            │                       │
            ▼                       ▼
    Return to Frontend      Return to Frontend
    with ALL numbers        with OWN numbers
                            (for own orders)
                            with NO numbers
                            (for others' orders)
```

---

## Implementation Change Points

```
Current Code Flow:
┌──────────────────────┐
│ Get Clients + Orders │  (MongoDB Aggregation)
├──────────────────────┤
│ Calculate USD rates  │  (Python Loop)
├──────────────────────┤
│ Get Photos & Receipts│  (Photo/Receipt lookups)
├──────────────────────┤
│ Build Detail Section │  (employee_names, etc)
├──────────────────────┤
│ Return Response      │
└──────────────────────┘

Modified Code Flow:
┌──────────────────────┐
│ Get Clients + Orders │  (MongoDB Aggregation)
├──────────────────────┤
│ Calculate USD rates  │  (Python Loop)
├──────────────────────┤
│ Get Photos & Receipts│  (Photo/Receipt lookups)
├──────────────────────┤
│ ★ Enrich WhatsApp #s │  ← NEW: Add this
│ (role-based filter)  │     (1 helper + 1 loop)
├──────────────────────┤
│ Build Detail Section │  (already has whatsapp_numbers)
├──────────────────────┤
│ Return Response      │
└──────────────────────┘
```

---

## Code Change Summary

### Single File Modified: `app/api/routes.py`

#### Addition 1: Helper Function
```
Location: Line ~2725 (after USD calculation)
Type: Function definition
Size: ~20 lines
Purpose: Get whatsapp_numbers based on role + handler
```

#### Addition 2: Enrichment Loop
```
Location: Line ~2745 (after helper function)
Type: For loop
Size: 2-3 lines
Purpose: Populate profile_whatsapp_number for each order
```

#### Total Changes
- Lines added: ~30
- Lines removed: 0
- Breaking changes: None
- Backward compatible: Yes ✓

---

## Testing Decision Tree

```
                    Start Tests
                        │
                        ▼
            Login as ADMIN user
                        │
         ┌──────────────┴──────────────┐
         │                             │
         ▼                             ▼
  Get Dashboard Orders           Check Response
         │                             │
         ▼                             ▼
  For each order:         Are WhatsApp numbers
  Compare                 populated for ALL
  profile_whatsapp_number employees?
  with users table            │
         │                    ├─ YES ✓ PASS
         │                    └─ NO  ✗ FAIL
         │
         ▼
   Get Data from
   users.whatsapp_numbers
         │
         ▼
   Compare each field
         │
    ┌────┴────┐
    │          │
   PASS      FAIL
    │          │
    ▼          ▼
  Continue   Debug
    │        Role
    │        Check
    ▼        Logic
  Test
  MANAGER
    │
    ▼
  Test
  EMPLOYEE
    │
    ├─ Own order: Show numbers ✓
    ├─ Other order: Empty list ✓
    │
    ▼
  All Tests Pass
    │
    ▼
  READY FOR DEPLOY
```

---

## Summary Table

| Aspect | Details |
|--------|---------|
| **Feature** | Add WhatsApp numbers to dashboard orders |
| **Data Source** | users.whatsapp_numbers |
| **Field Name** | profile_whatsapp_number |
| **Type** | List[str] (array) |
| **Admin/Manager** | See ALL employee numbers |
| **Employee** | See only OWN numbers |
| **Files Changed** | 1 (app/api/routes.py) |
| **Lines Added** | ~30 |
| **Lines Removed** | 0 |
| **Breaking Changes** | None |
| **Performance Impact** | <5% (~2ms per order) |
| **Database Changes** | None |
| **Cache Impact** | Compatible |
| **Testing Effort** | 3 scenarios |

---

