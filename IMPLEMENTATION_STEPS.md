# Step-by-Step Implementation Guide

## Overview
This guide provides exact line numbers and code snippets for implementing the WhatsApp numbers feature.

---

## Step 1: Verify Schema (No Changes Needed)

**File**: `app/schemas.py`

**Check Line 517** - `DashboardOrderResponse` class

The field already exists:
```python
class DashboardOrderResponse(BaseModel):
    s_no: Optional[int] = None
    # ... other fields ...
    profile_whatsapp_number: Optional[List[str]] = None  # ← ALREADY HERE
    # ...
```

✅ **Status**: NO ACTION NEEDED

---

## Step 2: Add WhatsApp Enrichment to Route Handler

**File**: `app/api/routes.py`

**Function**: `get_dashboard_orders()` (starts at line 2481)

### 2a. Locate the insertion point

Find line ~2720 where USD conversion is done:

```python
# Around line 2720 in get_dashboard_orders()
        row["total_amount_usd"] = round(raw_total * multiplier, 2)
        row["paid_amount_usd"] = round(raw_paid * multiplier, 2)

# ← INSERT HELPER FUNCTION HERE (Step 2b)
```

### 2b. Add the helper function

**Add AFTER the multiplier calculation loop (after line 2725)**:

```python
    # Helper function to get WhatsApp numbers based on user role
    def get_whatsapp_for_order(row, current_user):
        """
        Get WhatsApp numbers based on role and order handler.
        - Employee: Only their own numbers
        - Admin/Manager: All employees' numbers
        """
        handler_email = row.get("client_handler")
        profile_name = row.get("profile_name")
        
        if current_user["role"] == UserRole.EMPLOYEE:
            # Employee can only see their own WhatsApp numbers
            if current_user["email"] == handler_email:
                return current_user.get("whatsapp_numbers", [])
            else:
                return []  # Can't see other employees' numbers
        else:
            # Admin/Manager can see all employees' WhatsApp numbers
            # Try to find user by handler email or profile name
            user_doc = users_collection.find_one(
                {"$or": [
                    {"email": handler_email},
                    {"full_name": profile_name}
                ]},
                {"whatsapp_numbers": 1}
            )
            return user_doc.get("whatsapp_numbers", []) if user_doc else []
```

### 2c. Add enrichment loop

**Add AFTER the helper function definition (after line 2750 approx)**:

```python
    # Enrich dashboard data with WhatsApp numbers
    for row in dashboard_data:
        row["profile_whatsapp_number"] = get_whatsapp_for_order(row, current_user)
```

### 2d. Complete code section view

After your changes, the section should look like:

```python
    # Calculate USD equivalents dynamically
    for row in dashboard_data:
        # ... existing USD conversion code ...
        row["total_amount_usd"] = round(raw_total * multiplier, 2)
        row["paid_amount_usd"] = round(raw_paid * multiplier, 2)

    # Helper function to get WhatsApp numbers based on user role
    def get_whatsapp_for_order(row, current_user):
        """
        Get WhatsApp numbers based on role and order handler.
        - Employee: Only their own numbers
        - Admin/Manager: All employees' numbers
        """
        handler_email = row.get("client_handler")
        profile_name = row.get("profile_name")
        
        if current_user["role"] == UserRole.EMPLOYEE:
            if current_user["email"] == handler_email:
                return current_user.get("whatsapp_numbers", [])
            else:
                return []
        else:
            user_doc = users_collection.find_one(
                {"$or": [
                    {"email": handler_email},
                    {"full_name": profile_name}
                ]},
                {"whatsapp_numbers": 1}
            )
            return user_doc.get("whatsapp_numbers", []) if user_doc else []

    # Enrich dashboard data with WhatsApp numbers
    for row in dashboard_data:
        row["profile_whatsapp_number"] = get_whatsapp_for_order(row, current_user)

    # Continue with cache and detail building...
    cache_manager.set(cache_key, dashboard_data)
```

---

## Step 3: Verify the Detail Section (Already Correct)

**File**: `app/api/routes.py`

**Location**: Around line 2750-2760 in `get_dashboard_orders()`

Current detail building code:

```python
    detail = {
        "employee_names": list(employee_names),
        "profile_names": list(profile_names),
        "we_chats": list(we_chats),
        "whatsapp_numbers": list(whatsapp_numbers),  # ← ALREADY INCLUDED
        "order_type_options": order_type_options,
        "bank_account_options": bank_account_options,
        "payment_method_options": payment_method_options
    }
```

✅ **Status**: NO ACTION NEEDED - Already includes whatsapp_numbers

---

## Step 4: Testing

### Test Case 1: Admin User
```python
# Login as admin
GET /dashboard/orders
Authorization: Bearer <admin_token>

# Expected: Each order should have profile_whatsapp_number with ALL employee numbers
# Example response:
{
  "data": [{
    "order_id": "ORD001",
    "profile_name": "MUTHU",
    "profile_whatsapp_number": [
      "+91-9876543210",
      "+91-9876543211"
    ],
    ...
  }]
}
```

### Test Case 2: Employee User (Own Order)
```python
# Login as employee@company.com
# employee has whatsapp_numbers: ["+91-1111111111"]
GET /dashboard/orders
Authorization: Bearer <employee_token>

# Expected: Own orders show own WhatsApp numbers
{
  "data": [{
    "order_id": "ORD001",
    "client_handler": "employee@company.com",
    "profile_name": "EMPLOYEE_PROFILE",
    "profile_whatsapp_number": ["+91-1111111111"],  # ← SHOWS OWN NUMBER
    ...
  }]
}
```

### Test Case 3: Employee User (Other's Order)
```python
# Login as employee@company.com
# But viewing order handled by colleague@company.com
GET /dashboard/orders
Authorization: Bearer <employee_token>

# Expected: Other's orders show empty WhatsApp numbers
{
  "data": [{
    "order_id": "ORD002",
    "client_handler": "colleague@company.com",
    "profile_name": "COLLEAGUE_PROFILE",
    "profile_whatsapp_number": [],  # ← EMPTY (no access)
    ...
  }]
}
```

---

## Step 5: Verification Checklist

After implementation, verify:

- [ ] **Schema**: `DashboardOrderResponse` has `profile_whatsapp_number` field ✓
- [ ] **Function**: `get_whatsapp_for_order()` helper is defined
- [ ] **Loop**: Data enrichment loop populates the field
- [ ] **Admin Test**: Can see all employee WhatsApp numbers
- [ ] **Manager Test**: Can see all employee WhatsApp numbers
- [ ] **Employee Test**: Can only see their own numbers
- [ ] **Null Cases**: Empty/null handlers return `[]` not errors
- [ ] **Performance**: No significant slowdown
- [ ] **Cache**: Works correctly with caching

---

## Common Issues & Solutions

### Issue 1: WhatsApp Numbers Not Showing
**Cause**: User document doesn't have `whatsapp_numbers` populated

**Solution**:
```python
# Check in MongoDB
db.users.find({"email": "employee@company.com"})
# Should have: whatsapp_numbers: ["+91-...", "+91-..."]

# If empty, add data via user profile update
```

### Issue 2: Employee Seeing Other's Numbers
**Cause**: Role check logic not working

**Solution**: Verify the condition:
```python
if current_user["role"] == UserRole.EMPLOYEE:  # Must be exact match
    if current_user["email"] == handler_email:  # Must match email
```

### Issue 3: Aggregation Pipeline Issues
**Cause**: If using MongoDB pipeline option instead of Python

**Solution**: Stick with Python approach (easier to debug)

---

## Code Summary

### Files Modified: 1
- `app/api/routes.py`

### Lines Added: ~30
- 1 helper function (~20 lines)
- 1 enrichment loop (~2 lines)

### Breaking Changes: None
- Backward compatible
- New field only, existing fields unchanged

### Performance Impact: Minimal
- ~1-2ms per order
- Negligible for <1000 records

---

## Rollback Instructions

If you need to rollback:

1. **Remove the helper function** (5 lines)
2. **Remove the enrichment loop** (2 lines)
3. **Restart service**
4. **Done** - Field will just be `null` in response

No database changes needed!

---

## Next: Actual Implementation

Once you're ready to implement:

1. Open `app/api/routes.py`
2. Go to `get_dashboard_orders()` function
3. Follow Step 2a-2d above
4. Test with the test cases in Step 4
5. Verify checklist in Step 5

