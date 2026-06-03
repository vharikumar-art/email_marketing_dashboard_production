# Implementation Plan: WhatsApp Numbers for Dashboard Orders

## Overview
Add WhatsApp numbers from the users table to the `/dashboard/orders` endpoint with role-based access control.

---

## Current Architecture

### Database Structure
- **users collection**: Contains `whatsapp_numbers: List[str]` for each user
- **orders collection**: Contains `profile_name` (handler profile) and `whatsapp_number` (singular - specific one used)
- **clients collection**: Contains `client_handler` (email) linking to user

### Current API Response
```json
{
  "status_code": 200,
  "status": "success",
  "message": "Dashboard data fetched successfully",
  "data": [
    {
      "profile_name": "MUTHU",
      "we_chat": ["87459987555", "54756668711"],
      "whatsapp_numbers": [],  // Currently empty - NEEDS TO BE POPULATED
      ...
    }
  ],
  "detail": {
    "whatsapp_numbers": [...],  // All options
    "order_type_options": [...],
    ...
  }
}
```

---

## Requirements

### 1. Add WhatsApp Numbers Column
- Display all WhatsApp numbers available for the order handler
- Field name: `whatsapp_numbers` (plural)
- Type: `List[str]`

### 2. Role-Based Access Control
| User Role | Behavior |
|-----------|----------|
| **Admin** | See ALL employee WhatsApp numbers |
| **Manager** | See ALL employee WhatsApp numbers |
| **Employee** | See only their OWN WhatsApp numbers |

### 3. Data Sources
- Pull from `users` collection
- Filter by:
  - For employees: Their own email (current user)
  - For admin/manager: All employees in the system

---

## Implementation Details

### Step 1: Update Pydantic Schema
**File**: `app/schemas.py` → `DashboardOrderResponse` class

**Change**:
```python
# Current (no update needed, field already exists)
profile_whatsapp_number: Optional[List[str]] = None

# This field is already present but not being populated in the aggregation pipeline
```

**Status**: ✅ Already defined - just needs population

---

### Step 2: Modify Aggregation Pipeline
**File**: `app/api/routes.py` → `get_dashboard_orders()` function

**Current Flow**:
1. `$match` clients by handler (if employee)
2. `$lookup` orders
3. `$unwind` orders
4. `$lookup` payments
5. `$project` - constructs response

**Required Changes**:

#### Option A: Use MongoDB Aggregation (Recommended)
Add an additional `$lookup` stage to join users collection:

```javascript
{
  "$lookup": {
    "from": "users",
    "localField": "order.profile_name",  // or use order handler email
    "foreignField": "full_name",          // match with user full_name
    "as": "handler_user"
  }
},
{
  "$set": {
    "profile_whatsapp_number": {
      "$cond": [
        {"$gt": [{"$size": "$handler_user"}, 0]},
        {"$arrayElemAt": ["$handler_user.whatsapp_numbers", 0]},
        []
      ]
    }
  }
}
```

#### Option B: Post-Processing in Python (Simpler)
After aggregation, enrich data with WhatsApp numbers in application code:

1. Extract handler emails/profile names from results
2. Query users collection for their WhatsApp numbers
3. Populate `profile_whatsapp_number` field
4. Apply role-based filtering

**Recommended**: Option B (simpler, more flexible for role-based filtering)

---

### Step 3: Role-Based Filtering Logic

```python
# Pseudocode
def get_whatsapp_numbers(current_user, profile_name, handler_email):
    if current_user["role"] == UserRole.EMPLOYEE:
        # Only return their own
        if current_user["email"] == handler_email:
            return current_user.get("whatsapp_numbers", [])
        else:
            return []  # Can't see other employee's numbers
    else:
        # Admin/Manager can see all
        user = users_collection.find_one(
            {"$or": [{"full_name": profile_name}, {"email": handler_email}]}
        )
        return user.get("whatsapp_numbers", []) if user else []
```

---

### Step 4: Implementation Code Changes

#### In `get_dashboard_orders()` function:

**Add after cache check and before response (around line 2720)**:

```python
# Enrich with WhatsApp numbers
def get_whatsapp_for_order(row, current_user):
    """Get WhatsApp numbers based on role and order handler"""
    handler_email = row.get("client_handler")
    profile_name = row.get("profile_name")
    
    if current_user["role"] == UserRole.EMPLOYEE:
        # Employee can only see their own
        if current_user["email"] == handler_email:
            return current_user.get("whatsapp_numbers", [])
        return []
    else:
        # Admin/Manager can see all employees' numbers
        # Try to find user by handler email or profile name
        user_doc = users_collection.find_one(
            {"$or": [
                {"email": handler_email},
                {"full_name": profile_name}
            ]}
        )
        return user_doc.get("whatsapp_numbers", []) if user_doc else []

# Apply to all rows
for row in dashboard_data:
    row["profile_whatsapp_number"] = get_whatsapp_for_order(row, current_user)
```

---

## Detailed Changes Summary

### File 1: `app/schemas.py`
**Status**: ✅ NO CHANGES NEEDED
- Field `profile_whatsapp_number: Optional[List[str]] = None` already exists in `DashboardOrderResponse`

### File 2: `app/api/routes.py` → `get_dashboard_orders()`

**Changes**:
1. After line ~2720 (after setting `total_amount_usd` and `paid_amount_usd`)
2. Add helper function to get WhatsApp numbers based on role
3. Loop through `dashboard_data` and populate `profile_whatsapp_number`

**Code Location**: Between cache save and detail building section

---

## Testing Checklist

- [ ] **Admin Login**: Verify ALL employees' WhatsApp numbers appear for each order
- [ ] **Manager Login**: Verify ALL employees' WhatsApp numbers appear for each order
- [ ] **Employee Login**: Verify ONLY their own WhatsApp numbers appear
- [ ] **Empty Numbers**: Handle orders where handler has no WhatsApp numbers
- [ ] **Null Handlers**: Handle orders with missing handler data
- [ ] **Detail Section**: Verify `whatsapp_numbers` options are complete
- [ ] **Cache**: Verify cache is properly invalidated/updated
- [ ] **Performance**: Test with large dataset (100+ orders)

---

## Database Query Examples

### To verify data exists:
```javascript
// Check users have whatsapp_numbers
db.users.findOne({role: "employee"}, {whatsapp_numbers: 1})

// Check orders have profile_name
db.orders.findOne({}, {profile_name: 1, we_chat: 1, whatsapp_number: 1})
```

---

## Edge Cases to Handle

1. **User with no WhatsApp numbers** → Return empty list `[]`
2. **Order with no profile_name** → Return empty list or null
3. **Employee viewing other's orders** → Return empty list (not show numbers)
4. **Deleted/Inactive users** → Handle gracefully (skip or return empty)
5. **Duplicate profile names** → Use email as fallback

---

## Performance Considerations

- **Current**: Single aggregation pipeline + post-processing
- **Proposed**: Add minimal post-processing (~50-100ms for users lookup)
- **Optimization**: Cache employee list after initial fetch (already cached)
- **Impact**: Negligible for <1000 orders

---

## Rollback Plan

If issues arise:
1. Remove the `profile_whatsapp_number` population code
2. Field will default to `null` in response
3. Frontend can handle gracefully
4. No database changes needed

---

## Next Steps

1. ✅ Create this plan (DONE)
2. Implement changes in `app/schemas.py` (if needed)
3. Implement changes in `app/api/routes.py`
4. Test with all three user roles
5. Verify with screenshot comparison
6. Deploy and monitor

