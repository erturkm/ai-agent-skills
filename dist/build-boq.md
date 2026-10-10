---
name: "build-boq"
description: "Build a professional Microsoft licensing BoQ from an ERP price workbook using a supplied Excel BoQ template, with exact SKU mapping, base/attach scenarios, formulas, and validation."
---


# Build BoQ

Create a complete, professional Microsoft licensing Bill of Quantities (BoQ) in Excel from a customer request, an ERP or price-list workbook, and a supplied BoQ template.

## Required inputs

Identify or ask for these only when unavailable:
- Customer or deal name.
- Requested products and quantities.
- ERP or price-list workbook.
- Excel BoQ template.
- Pricing basis, currency, and effective date if not evident from the source.
- Whether alternate base/attach licensing scenarios are required.
- Any approved discount, exchange rate, tax treatment, and local commercial assumptions.

## Mandatory spreadsheet workflow

1. Load the `xlsx` skill before reading or modifying spreadsheet files.
2. Locate the supplied ERP workbook and BoQ template. Prefer explicitly attached/tagged files over similarly named files.
3. Inspect the template structure, styles, formulas, merged cells, widths, print settings, and expected columns. Preserve its visual conventions and create a new output copy; never overwrite the user's source template.
4. Inspect the ERP workbook headers and determine the authoritative pricing column. If the user identifies ERP as Estimated Retail Price, use the ERP column rather than Net Price.
5. Resolve each requested product to an exact current SKU. Search all matching rows and compare item name, product family, purchase unit, purchase period, display/public status, effective dates, and ERP price.
6. Prefer current per-user subscription SKUs for Dynamics 365 when requested. Avoid legacy CAL, SASU, government, device, renewal, promotional, qualified-offer, or obsolete SKUs unless the user explicitly requests them.
7. For attach pricing, include the qualifying base license in the scenario and clearly state the prerequisite in the description. Do not silently substitute attach for standalone pricing.
8. If a product mapping is genuinely ambiguous, present the best 2-5 candidates with SKU, item name, unit, and ERP price and ask the user to choose. Never invent a SKU or price.
9. Use one row per SKU with these fields when supported by the template: License Name, SKU Code, Quantity, Unit Cost, Monthly Cost, Annual Cost, and Description.
10. Use formulas for calculations: Monthly Cost = Quantity * Unit Cost; Annual Cost = Monthly Cost * 12; totals must use SUM formulas. Do not hardcode calculated totals.
11. When the user asks for alternatives, keep the original table and add a clearly titled scenario table beneath it using the same columns and formatting.
12. Add concise descriptions that explain license purpose and important prerequisites. Note currency, tax exclusion, pricing source, and effective month.
13. Add source comments to hardcoded unit-price cells when practical, identifying the ERP workbook, effective month, and ERP column.
14. Save the final workbook with a descriptive name such as `<Customer> CRM BoQ.xlsx` in an appropriate workspace subfolder.
15. Recalculate formulas using the `xlsx` skill's recalculation workflow, scan for formula errors, and verify line quantities, SKUs, unit prices, monthly totals, annual totals, workbook integrity, and print area before delivery.
16. Remove temporary conversion artifacts. Deliver only the final workbook unless the user requests supporting files.

## Licensing scenario guidance

- Base scenario: use standalone/base licenses when no qualifying base product exists.
- Attach scenario: use attach licenses only where the requested base SKU qualifies; label the scenario and prerequisites.
- Copilot Studio: distinguish user licenses from tenant capacity/message/credit packs; include each requested component as a separate row.
- Power Automate dedicated integrations: use process/per-flow licensing when requested, with quantity equal to the number of dedicated flows/processes.
- Customer Insights - Journeys: distinguish full application from attach application and interacted-people capacity add-ons. Use attach pricing only when a qualifying Dynamics 365 base license is included.

## Output quality

- Preserve the supplied template whenever technically possible.
- Match the template font, colors, borders, alignment, number formats, and column widths.
- Show hardcoded inputs in the template's convention; formulas must remain formulas.
- Use professional currency formatting and readable descriptions.
- Deliver with zero formula errors and no broken references.
- In the final response, link the workbook and state the scenario totals succinctly.

## CCaaS / Contact Center BoQs

Whenever the BoQ is for a contact center, CCaaS, Dynamics 365 Contact Center, Customer Service, IVR, voicebot, chatbot, or Copilot Studio agent deal, use the supplied customer template unless the user asks you to build a clean workbook from scratch.

### Recommended workbook structure

Use this sheet set unless the supplied template requires a different structure:

1. **`<Customer> BoQ`** - sizing input block, derived-volume block, Copilot credits breakdown, license table, telephony/voice-cost block when in scope, scenario tables, and grand totals.
2. **`Range Scenarios`** - Low / Base / High columns driven off the same formulas. Mandatory whenever the customer cannot commit to firm volumes.
3. **`Initiative Summary`** - the customer's commercial summary table, one row per project or initiative, with a reconciliation formula that evaluates to zero against the main sheet grand total.
4. **`Notes & Open Questions`** - assumptions, exclusions, pricing basis, and every open question.

### Recommended columns

Use these columns when the template does not prescribe another layout:

`License Business Name | License Name | SKU Code | Quantity | Unit Cost | Monthly Cost | Annual Cost | Discount | Discounted Price | Description | Effective Unit Cost | Local Currency Unit Cost | Local Currency Total Cost`

### Formula conventions

- Monthly Cost = Unit Cost * Quantity.
- Annual Cost = Monthly Cost * 12.
- Discounted Price = Annual Cost * (1 - Discount).
- Effective Unit Cost = (Discounted Price / 12) / Quantity.
- Local Currency Unit Cost = Effective Unit Cost * exchange rate.
- Local Currency Total Cost = Local Currency Unit Cost * Quantity.
- Totals must use `SUM` formulas.
- Discounts, exchange rates, and tax treatment must come from the user, the workbook, or the approved commercial source. Never hardcode local commercial assumptions.

### Copilot and contact-center metering

- **Generative** workloads, such as chatbots, AI voice bots, outcome capture, and intent capture, are normally metered with Copilot Studio capacity or message/credit packs. Validate the current unit, pack size, and price from the ERP workbook.
- **Deterministic** guided IVR may use product-specific voicebot or IVR meters instead of generative credits. Do not meter the same traffic twice.
- Cite the Microsoft Copilot Studio estimator when using published credit-rate assumptions: `https://microsoft.github.io/copilot-studio-estimator/`.
- For pooled entitlements, size the included pool from the licensed seat count, subtract included capacity before pricing overage, and state how overage lines change if the licensed seat estate changes.
- If the same call volume appears under more than one customer initiative, treat it as one population and say so prominently. Pricing it twice inflates the BoQ.

### ERP price-list handling

- If the price workbook contains duplicate part numbers with different effective dates, filter to public/current rows first, then take the row with the latest valid start date.
- Confirm the header row and data start row by inspecting the workbook; do not assume fixed row numbers.
- Confirm whether the requested price basis is list price, estimated retail price, net price, or another commercial column.

### Product rules

- Confirm what the customer already owns before choosing a standalone or attach SKU. If the customer has a qualifying base license, use the attach SKU only when the ERP workbook and product terms confirm eligibility.
- Never add a base license the customer already owns. If some users are outside the existing estate, price standalone licensing as a clearly labelled alternative scenario and show the incremental delta.
- Telephony costs depend on the chosen architecture. Price Azure Communication Services, Teams Phone, Calling Plan, Direct Routing, or carrier costs only when they are explicitly in scope and supported by the customer's design.
- Customer Insights - Journeys capacity should be sized from the appropriate unique interacted-person or capacity metric, not from raw message count, unless the product terms and ERP workbook specify otherwise.

### Layout hygiene

- Every block gets its own full-width banner row, header row, and blank spacer row before the next block.
- Never let a note column run under an adjacent table.
- Make editable inputs visually distinct from derived/calculated cells.
- Give every input a **Unit** column and a **Source / rationale** column. Never leave an assumption unattributed.
- Freeze panes below the first header row on every sheet.
