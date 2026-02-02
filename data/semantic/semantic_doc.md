# EMS Semantic Documentation
Scope: Account, Warehouse & Portal Services  
Status: ACTIVE – AUTHORITATIVE  

Purpose: Provide business semantics, intent, and binding rules for SQL generation and validation in the EMS Expense Management Agent.

IMPORTANT:  
This document defines SEMANTICS and RULES only.  
Physical schema (tables, columns, keys) is loaded exclusively from `schemas_from_mdl.json`.

----------------------------------------------------------------
1. GLOBAL CONVENTIONS
----------------------------------------------------------------

1.1 Identifier Rules
- All columns ending with `_id` are surrogate keys.
- Surrogate keys do NOT carry business meaning.
- Human-readable values MUST always be resolved via lookup tables.

1.2 Canonical Lookup Table
- Global dictionary table:
  ems-portal-service.quick_code_master
- Canonical human-readable column:
  quick_code_master.name

1.3 Audit Fields
- Audit fields are ignored everywhere:
  created_at, updated_at, created_by, updated_by

EXCEPTION:
- Invoice tables retain audit fields as they carry business meaning
  (ownership, approval responsibility, approval duration).

----------------------------------------------------------------
2. TERMINOLOGY (AUTHORITATIVE)
----------------------------------------------------------------

warehouse:
- A physical location where expenses are incurred.
- Defined in ems-warehouse-service.warehouse_info.

account:
- A customer entity.
- A single account can operate in multiple warehouses.
- A warehouse can host multiple accounts.
- Account name matching is ALWAYS fuzzy, never exact.

expense:
- A financial cost incurred and billed via invoices.
- Categorized via expenses_master and quick_code_master.

expense type:
- A broad classification (e.g., Rent, Manpower).

expense category:
- A sub-classification (e.g., Cash, Corporate).
- Resolved via quick_code_master.

vendor:
- The external entity that raises a bill.
- Identified via ems-auth-service.user.

quick_code_master:
- The global dictionary table.
- Resolves all coded values such as:
  city, state, zone, region, industry,
  expense mode, expense category.

----------------------------------------------------------------
3. SERVICE-WISE SEMANTICS
----------------------------------------------------------------

3.1 EMS-PORTAL-SERVICE (Invoices)

invoice_info:
- Represents the HEADER of a bill/invoice.
- Each row is a single approval request.
- TRANSACTIONAL FACT table.

Key semantics:
- invoice_info.total_amount is the FINAL billable amount.
- invoice_status: Binary {0,1}
- approval_status: MUST join with ems-portal-service.master_status
- invoice_expense_type: {SINGLE, MULTI}

Actor semantics:
- created_by, updated_by → ems-auth-service.user.full_name
- vendor_id → ems-auth-service.user.full_name

invoice_line_items:
- Detailed invoice breakdown.
- One invoice_info → many invoice_line_items.
- total_mtd is used ONLY for budget validation.

invoice_line_items_expense:
- MUST NEVER be queried.
- INVALID for reporting or aggregation.

----------------------------------------------------------------
3.2 EMS-WAREHOUSE-SERVICE (Locations)
----------------------------------------------------------------

warehouse_info:
- Registry of all physical warehouses.

Geographic & classification fields:
- city_id, state_id, zone_id, region_id, ownership_type_id
- MUST be resolved via ems-portal-service.quick_code_master

Lifecycle:
- start_date: operational start
- closing_date = NULL means active

warehouse_expense_mapping:
- Validation table.
- Defines which expenses are allowed at a warehouse.
- Used ONLY as a filter, never as a fact source.

----------------------------------------------------------------
3.3 EMS-ACCOUNT-SERVICE (Customers)
----------------------------------------------------------------

account_info:
- Registry of all customer accounts.
- Geographic fields resolved via quick_code_master.

account_warehouse_info:
- CONTEXTUAL relationship table.
- Defines account–warehouse operational relationships.

Rules:
- Used ONLY when explicitly asking about:
  - account–warehouse relationships
  - operational presence
  - start_date / closing_date
  - allowed or configured expenses
- MUST NOT be used for invoice aggregation.

account_expense_mapping:
- Validation table.
- NEVER used for aggregation.

----------------------------------------------------------------
4. JOIN POLICY (AUTHORITATIVE)
----------------------------------------------------------------

FACT TABLES:
- ems-portal-service.invoice_info

RULES:
1. invoice_info is the PRIMARY fact table for reporting.
2. invoice_info already contains account_id and warehouse_id.
3. Legal joins for invoice queries:
   - invoice_info.account_id → ems-account-service.account_info.id
   - invoice_info.warehouse_id → ems-warehouse-service.warehouse_info.id
4. account_warehouse_info is a CONTEXT table:
   - MUST NOT be used for invoice aggregation.
5. Any query joining invoice_info AND account_warehouse_info
   is INVALID unless explicitly about relationships.
6. quick_code_master MUST always be joined via quick_code_master.id.

NOTE:
Scalar subqueries against master_status MAY be used
ONLY if they resolve to a single, unique status value
and are used solely for filtering.

JOIN-based resolution remains the canonical
and preferred pattern.


----------------------------------------------------------------
5. MONETARY SOURCE OF TRUTH (AUTHORITATIVE)
----------------------------------------------------------------

Rules:
1. invoice_info.total_amount is the ONLY authoritative monetary value.
2. Monetary aggregation MUST use ONLY invoice_info.total_amount.
3. invoice_line_items MUST NOT be used unless explicitly requested.
4. invoice_line_items_expense MUST NEVER be queried.

----------------------------------------------------------------
6. PENDING & APPROVAL SEMANTICS
----------------------------------------------------------------

Pending Approval Duration:
- Applies to invoices NOT approved.
- Pending Duration = CURRENT_TIMESTAMP - invoice_info.created_at
- Exclude APPROVED and REJECTED invoices.

Approval Time:
- Applies ONLY to invoices whose approval is completed.
- Approval Time = invoice_info.updated_at - invoice_info.created_at
- NOW() MUST NOT be used for approval duration.

Ranking rules:
- “longest”, “slowest”, “most time” → MAX(duration)

----------------------------------------------------------------
7. HUMAN-ENTERED IDENTIFIER MATCHING (MANDATORY)
----------------------------------------------------------------

Rules:
- ALL human-entered names MUST use LIKE-based matching.
- Exact equality (=) is INVALID.

Applies to:
- Account names
- Vendor names
- Warehouse names
- City names
- Region names
- Zone names
- Expense names
- Category names
- quick_code_master.name

Standard pattern:
  column_name LIKE '%value%'

----------------------------------------------------------------
8. APPROVAL STATUS SEMANTICS (AUTHORITATIVE)
----------------------------------------------------------------

Rules:
1. approval_status MUST ALWAYS be resolved via master_status.
2. Numeric approval_status values MUST NEVER be used.
3. Business logic MUST operate ONLY on master_status.name.

Canonical join:
invoice_info.approval_status
→ master_status.id
→ master_status.name

----------------------------------------------------------------
9. RATIO & PERCENTAGE METRICS (AUTHORITATIVE)
----------------------------------------------------------------

Rejection Rate:
- rejected / (approved + rejected)

Rejection-to-Approval Ratio:
- rejected / approved
- Pending or non-final states MUST be excluded.
- Division by zero MUST be guarded (NULLIF).

Rules:
- The metric name MUST match the math.
- Rate ≠ Ratio.
- Filtering the denominator in WHERE is INVALID.

----------------------------------------------------------------
10. TIME SEMANTICS & CALENDAR LOGIC (STRICT)
----------------------------------------------------------------

10.1 "Last X Months" / "Past X Months"
- Definition: X fully COMPLETED calendar months.
- Excludes: The current partial month.
- Start Date: 1st day of the month X months ago.
- End Date: 1st day of the CURRENT month (exclusive).

CORRECT PATTERN (MySQL):
WHERE invoice_month >= DATE_FORMAT(DATE_SUB(CURDATE(), INTERVAL 6 MONTH), '%Y-%m-01')
  AND invoice_month < DATE_FORMAT(CURDATE(), '%Y-%m-01')

PROHIBITED PATTERNS (DO NOT USE):
- invoice_date > NOW() - INTERVAL 6 MONTH (Rolling window is forbidden)
- BETWEEN ... AND NOW() (Includes current partial month)

10.2 Trending & Grouping
- ALWAYS group by `invoice_month` (Bill Date), NEVER `invoice_date` (Upload Date).
- If the user asks for "monthly trend" or "by month", you MUST select and group by `invoice_month`.

10.3 Specific Months ("In November", "Last November")
- "In November": Means November of the CURRENT year (unless context implies past).
- "Last November": Means November of the PREVIOUS year.
- Always use explicit date ranges:
  invoice_month >= '2025-11-01' AND invoice_month < '2025-12-01'

10.4 Fiscal Year
- If "Fiscal Year" is mentioned (e.g., FY24), assume April 1st to March 31st.

----------------------------------------------------------------
11. SCHEMA NAME INTEGRITY RULE (CRITICAL)
----------------------------------------------------------------

Valid schemas (MUST be used verbatim):
- `ems-portal-service`
- `ems-warehouse-service`
- `ems-account-service`
- `ems-auth-service`

Rules:
- Hyphens are significant.
- Schema names MUST be backticked.
- Tables MUST be aliased.
- Column references MUST use aliases.

Any violation is INVALID.


### Approval Status Name Resolution (MANDATORY)

- Any approval status mentioned in user input
  (e.g., approved, rejected, pending, commented)
  MUST be resolved via ems-portal-service.master_status.

- Status resolution MUST use case-insensitive fuzzy matching.

MANDATORY pattern:
    LOWER(master_status.name) LIKE LOWER('%<status_from_user>%')

STRICT PROHIBITIONS:
- Using numeric approval_status codes (e.g., approval_status = 1)
- Using exact equality on master_status.name (e.g., name = 'APPROVED')
- Hardcoding status values without joining master_status


----------------------------------------------------------------
12. EXPENSE CATEGORY SEMANTICS (AUTHORITATIVE)
----------------------------------------------------------------

Definition:
Expense categories are cost classifications such as:
Rent, Manpower, Security, Electricity, Diesel, Transport, MHE Rent, etc.

Authoritative Source:
ems-portal-service.expenses_master.name

Canonical Resolution Path:
invoice_info
→ invoice_line_items (MANY-to-ONE with invoice_info)
→ expenses_master

Rules:
1. Expense categories MUST be resolved via expenses_master.expense_name.
2. Filtering by expense category REQUIRES joining invoice_line_items.
3. invoice_line_items is used ONLY for filtering, NEVER for aggregation.
4. Aggregation MUST use invoice_info.total_amount.
5. Expense categories are NOT accounts, vendors, or metrics.

STRICTLY PROHIBITED:
- Filtering expense categories using account_info.account_name
- Summing invoice_line_items values
- Treating numeric values as expense identifiers

