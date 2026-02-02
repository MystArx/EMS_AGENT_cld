## Account

A business entity or customer.

Rules:
- Account names are human-entered identifiers.
- Account name matching is always fuzzy, never exact.
- User input may be partial or informal.
- If a company or brand name is mentioned, assume Account unless stated otherwise.


## Vendor

A party to whom expenses are paid.

Rules:
- Vendors are payees, not customers.
- Do NOT confuse vendors with accounts.


## Warehouse

A physical operational facility.

Rules:
- Warehouses may be referenced by:
  - explicit warehouse name
  - city association

Disambiguation:
- If a city has only one warehouse, "<city> warehouse" may refer to that warehouse.
- If a city has multiple warehouses, "<city> warehouse" is ambiguous and requires clarification:
  - a specific warehouse
  - or all warehouses in that city


## City

A geographical city.

Rules:
- Cities are locations, not operational entities.
- If the user says "in <city>", interpret as City unless "warehouse" is explicitly mentioned.


## Region

A grouping of cities.

Rules:
- Regions are not cities.
- Terms like "north", "south", "eastern", etc. refer to Region unless corrected.
- Region-level queries aggregate across all cities and warehouses in that region.


## Metric – Total Expense

Definition:
- Sum of expense amounts.

Rules:
- Synonyms include: expense, expenses, total spend, spending.
- If user says "expense" or "expenses", default to Total Expense.


## Metric – Total Invoice Amount

Definition:
- Sum of invoice totals.

Rules:
- Synonyms include: invoice value, billing amount.


## Metric Continuity

Rules:
- Metrics persist across follow-up questions.
- If a follow-up does not explicitly mention a new metric, reuse the previous metric.
- Comparative terms like "most", "least", "higher", "lower" refer to the active metric.


## Time Semantics

Rules:
- Time references use CALENDAR periods, not rolling intervals
- "last month" = previous calendar month (all days)
- "last 6 months" = previous 6 complete calendar months
- "this month" = current calendar month from day 1
- "today" = current date
- "yesterday" = previous date

Examples (assuming today is January 13, 2026):
- "last month" → December 1-31, 2025
- "last 6 months" → July 1 - December 31, 2025
- "this month" → January 1-13, 2026
- "last year" → January 1 - December 31, 2025

If time is not specified, assume all time.
Follow-ups inherit the previous time filter unless changed.


## Corrections

Rules:
- Users may correct themselves mid-conversation.
- Corrections override only the corrected aspect.
- Unrelated context must be preserved.


## Output Discipline

Rules:
- Produce one clear analytical question.
- Update only relevant state fields.
- Do not mention databases, tables, columns, or SQL.

## Name Matching Semantics

Rules:
- All business-facing names are human-entered and non-canonical.
- Name references are always fuzzy, never exact.
- User input may be partial, abbreviated, or informal.
- Preserve the literal text provided by the user.

Applies to:
- Account names
- Vendor names
- Warehouse names
- City names
- Region names
- Any other business-facing label

Interpretation:
- Matching must tolerate variations in case, spacing, punctuation, and abbreviations.
- The refiner must treat all such names as requiring fuzzy resolution.

## Approval Time Semantics

Definition:
- Approval time refers to the duration between invoice submission and final approval.

Rules:
- Approval time applies only to invoices that have completed approval.
- Questions referring to "approved", "approval time", or "time to get approved"
  imply completed approval unless explicitly stated otherwise.
- Comparative terms such as "longest", "slowest", "maximum", or "most time"
  refer to the invoice with the greatest approval duration.

Interpretation:
- Approval time is treated as a duration metric.
- Queries asking for extremes select the maximum approval duration.

## Pending Approval Semantics

Definition:
- Pending approval refers to invoices that have been submitted
  but have not yet completed approval.

Rules:
- Questions using terms such as "pending", "stuck", or "not yet approved"
  refer to invoices awaiting approval.
- Pending approval duration is measured from submission time until now.
- Rejected invoices are excluded unless explicitly requested.

Interpretation:
- Pending approval is treated as a duration metric.
- Comparative terms select the invoice pending for the longest time.

## Attribute Preservation

Any explicit business-facing field or description requested by the user that is not a metric or filter.

**Examples:**
- remarks, comments, notes
- approval status
- invoice number, internal invoice number
- invoice date
- vendor name
- created by / approved by

**Rules:**
- If the user explicitly mentions an attribute, the refined analytical question **MUST** include that attribute.
- Attributes **MUST NOT** be dropped, generalized, or inferred away.
- Queries requesting specific attributes (e.g., "remarks from invoices", "approval status") **MUST NOT** be rewritten as generic invoice listings.
- Attribute requests take precedence over default listing behavior.
- Violation of this rule produces an **INVALID** refinement.

## Contextual Follow-up & Pronoun Resolution

Definition:
- Contextual follow-ups are user queries that rely on previously identified entities
  instead of explicitly restating them.

Examples:
- he, she, they
- this vendor, that account
- those warehouses
- where does he operate
- show their invoices
- in which warehouses is this happening

Rules:
- Follow-up queries MUST resolve references using conversation context.
- The system MUST NOT reinterpret a follow-up as a new standalone question.
- The system MUST NOT introduce new entities, metrics, or rankings unless explicitly stated.

### Pronoun Binding Priority

When resolving implicit references, bind in the following order:

1. Vendor (last referenced vendor)
2. Account (last referenced account)
3. Warehouse (last referenced warehouse)
4. City
5. Region

If no prior entity exists, request clarification.

### No Reinterpretation Rule (MANDATORY)

For contextual follow-ups:
- Do NOT change the analytical intent.
- Do NOT replace the referenced entity with a different aggregation target.
- Do NOT convert a follow-up into a global ranking or summary.

The refined analytical question MUST remain scoped to the resolved entity.

### Examples (AUTHORITATIVE)

Conversation:
User: "Which vendor has the most rejected invoices?"
Assistant: "Deo-Gaurav"

User: "In which warehouses he operates"

Correct refinement:
- Vendor = Deo-Gaurav
- Intent = list warehouses associated with that vendor

INVALID refinements:
- "Which warehouse has the most rejected invoices?"
- "Which vendors operate in most warehouses?"
- "List rejected invoices by warehouse"

### Metric & Time Continuity

Rules:
- Follow-up queries inherit:
  - the previously active metric
  - the previously active time filter
- Unless explicitly overridden, these MUST remain unchanged.

### Scope Preservation

Rules:
- If the prior query was entity-scoped, the follow-up MUST remain entity-scoped.
- Entity expansion (e.g., vendor → all vendors) is INVALID unless explicitly requested.

Violation of any rule in this section results in an **INVALID refinement**.

## Follow-Up Query Handling

Definition:
- Follow-up queries reference entities or results from the previous query
  without explicitly restating them.

Examples:
- Previous: Returned 15 vendors who haven't uploaded consistently
- User: "which vendor..." or "missing months for KBR"

Rules:
- If previous query returned a LIST of entities (vendors, accounts, warehouses),
  follow-up questions like "which one", "that vendor", "for KBR" refer to entities FROM THAT LIST
- Do NOT reinterpret follow-ups as new global queries
- Preserve the context and scope from the previous query
- Entity names mentioned in follow-ups should match names from previous results (fuzzy matching)

Examples (MANDATORY):
User: "Vendors who haven't uploaded consistently in last 6 months"
→ Returns: 15 vendors including "KBR Enterprises", "Safe X Security", etc.

User: "which vendor..."
CORRECT: "Which vendor from the previous list..."
WRONG: "Which vendor globally has..."

User: "missing months for KBR"  
CORRECT: "Which months are missing for vendor KBR Enterprises from the previous result?"
WRONG: "Which vendor named KBR has missing months?"

## Temporal Follow-Up Analysis

When user asks follow-up questions about temporal patterns (e.g., "which months", "when", "missing months"):

Rules:
- If previous query identified entities with temporal gaps, follow-up inherits those entities
- "Which months" questions require month-by-month breakdown
- "Missing months" requires generating expected months and finding gaps
- Always maintain entity scope from previous query

Example:
Previous: "Vendors inconsistent in last 6 months" → Returns 15 vendors
Follow-up: "In which months were they inconsistent?"
→ Analyze ONLY those 15 vendors, show per-vendor monthly breakdown

### Result Context Awareness

When the previous query returned data:
- Track the entity type returned (vendors, accounts, warehouses)
- Track entity names (for fuzzy matching in follow-ups)
- Track the metric or question context

Follow-up questions inherit this context unless explicitly overridden.

Violation of this rule results in INVALID refinement.

## Projection Continuity (CRITICAL)

Definition:
A follow-up that changes only the OUTPUT COLUMNS, not the analytical scope.

Examples:
- "also list names"
- "show vendor names"
- "give details"
- "break it down"

Rules:
- Do NOT change metric, region, time, or entity scope.
- Preserve all filters from the previous analytical question.
- Convert aggregates into distinct listings when requested.

Examples:
Previous: "Total number of vendors in the North region"
Follow-up: "also list names"

Correct refinement:
"List distinct vendor names operating in the North region"

INVALID:
- Global vendor listing
- New ranking
- Dropping region filter
