---
name: "cij-marketing"
description: "Build Microsoft Dynamics 365 Customer Insights - Journeys (CIJ) real-time marketing demos and assets via the Dataverse Web API: accounts, contacts, custom columns, segments, branded emails, content blocks, email templates, SMS/text messages, push notifications, and multi-touchpoint journeys. Use whenever the user wants to create or wire up CIJ / real-time marketing data, mentions segments, marketing emails, journeys, customer journeys, content blocks, marketing SMS or push, or a 'marketing demo' in a Dynamics 365 / Dataverse org."
---

You are helping me build a polished Microsoft Dynamics 365 **Customer Insights –
Journeys** (CIJ / real-time marketing) demo on a Dataverse org. Treat this as a
real engineering project, not advice — hit the Dataverse Web API directly with a
reusable helper, verify every record was created and went live, and never claim
something works until you've read it back. Below are the exact rules, schemas,
and hard-won gotchas this team uses. Following them avoids hours of trial/error.

⚠️ These notes are battle-tested against a live org. Where a value is marked
"capture from the org," read it from an existing working record rather than
inventing it — IDs differ per environment.

 

═══════════════════════════════════════════════════════════════════════════════
0. DISCOVER MY CONTEXT FIRST
═══════════════════════════════════════════════════════════════════════════════
Before building, establish and remember for the session:
  • The customer/brand the demo is FOR (e.g. "Inception", "inceptionai.ai") and
    its products — segments/emails should reference real product names.
  • The industry mix for accounts (banks, energy, telecom, govt, healthcare…).
  • My demo org URL (https://orgXXXXXX.crmN.dynamics.com). Note the region digit
    in crmN (e.g. crm4 = EMEA) — keep it; never "correct" crm4 to crm.
  • A custom-column publisher prefix (e.g. incpt_) if we'll tailor the data model.
Don't hardcode another demo's prefix, segment names, or product list.

 

═══════════════════════════════════════════════════════════════════════════════
1. ENVIRONMENT & AUTH (DO THIS ONCE)
═══════════════════════════════════════════════════════════════════════════════
• pac CLI needs a recent .NET. If `pac` complains, point DOTNET_ROOT at an
  installed runtime (e.g. Homebrew's: DOTNET_ROOT=/opt/homebrew/Cellar/dotnet/
  <ver>/libexec) rather than reinstalling.
• Reuse an existing auth profile: `pac auth list` → `pac auth select --index N`
  → confirm with `pac org who`. Only run `pac auth create --url <ORG_URL>` if no
  profile targets the org.
• Build ONE portable `scripts/dv.py` helper and route ALL work through it:
    - Acquires a token via MSAL. A working trick: reuse an existing MSAL token
      cache on the machine (e.g. ~/.dataverse-*/msal-cache.json) for the same
      tenant/user; iterate the client_ids found in its RefreshToken entries.
      Authority = https://login.microsoftonline.com/<tenantId>,
      scope = <ORG_URL>/.default. Auto-refresh on HTTP 401.
    - Exposes ONE function: api(method, path, body=None, headers=None).
    - URL-ENCODING IS MANDATORY AND urllib WON'T DO IT: replace every OData
      `$` option ($filter,$select,$expand,$top,$orderby,$count,$apply) with
      `%24...` AND encode spaces as `%20`. Without this you get spurious 400s.
    - On POST, surface the new GUID: Dataverse returns it in the
      `OData-EntityId` response header (inject it into the parsed result, e.g.
      as `_OData-EntityId`), OR pass header `Prefer: return=representation` to
      get the full row body back (cleaner — preferred for create+read).
• UI (make.powerapps.com / CIJ app) is for VERIFICATION ONLY, not for building.

 

═══════════════════════════════════════════════════════════════════════════════
2. PRINCIPLES
═══════════════════════════════════════════════════════════════════════════════
• Web API > UI clicks for everything: contacts, accounts, segments, emails,
  fragments, templates, SMS, push, journeys are all Dataverse rows.
• REAL-TIME ("msdynmkt_*") vs OUTBOUND ("msdyncrm_*"): modern CIJ orgs have
  BOTH entity families. Always build on the real-time `msdynmkt_*` entities
  (segment, email, journey, fragment, sms, pushnotification). Detect which the
  org uses by listing both; mirror whatever the org's recent live assets use.
• Inspect-before-build: read an existing WORKING asset of the same type and
  copy its exact field shape, lookup bindings, and config IDs. This is the
  single biggest time-saver — most "validation failed" issues are a missing
  field that the working record has.
• Read the actual error BODY on failure — Dataverse names the offending column,
  relationship, or (for segments) the parse position. Never guess.
• Verify go-live by reading statecode/statuscode back, not by assuming the
  POST/PATCH succeeded.

 

═══════════════════════════════════════════════════════════════════════════════
3. METADATA QUERY GOTCHAS
═══════════════════════════════════════════════════════════════════════════════
• `startswith()` is NOT supported on EntityDefinitions (HTTP 501). Pull the
  set and filter client-side in Python.
• To resolve a lookup's @odata.bind nav name + target set name:
    EntityDefinitions(LogicalName='X')/ManyToOneRelationships
      → ReferencingEntityNavigationPropertyName  (use as the @odata.bind key)
    EntityDefinitions(LogicalName='<ReferencedEntity>')?$select=EntitySetName
      → the set name to put in the bind path.
  Do NOT assume pluralization. Real example that bit us: the compliance lookup
  set is `msdynmkt_compliancesettings4s` (note the literal "4"), nav name
  `msdynmkt_compliance` on push/sms but `msdynmkt_compliancesettings4` on email.
• Choice/option values: read them live via
    EntityDefinitions(LogicalName='X')/Attributes(LogicalName='Y')/
    Microsoft.Dynamics.CRM.PicklistAttributeMetadata?$expand=OptionSet

 

═══════════════════════════════════════════════════════════════════════════════
4. CONTACTS & ACCOUNTS
═══════════════════════════════════════════════════════════════════════════════
• Tag every demo row in `description` with a marker like `[<Demo>Demo]` so you
  can find/clean them later.
• Link contact → account: `parentcustomerid_account@odata.bind` =
  `/accounts(<id>)`.
• industrycode native values you'll actually use (no native Government/Telecom
  codes exist — pick the closest): 16=Financial, 24=Petrochemical/Energy,
  31=Utilities, 6=Business Services (use for telecom/tech), 30=Transportation,
  11=Clinics/Healthcare, 27=Social Services (use for govt). Always confirm
  against the org's own optionset.

★ SAFETY — SANITIZE DEMO CONTACTS (do this proactively, it's a real concern):
  Marketing journeys SEND real email/SMS. For any FICTIONAL demo contact,
  redirect to a safe domain (e.g. <name>@<demo>demo.com) and an undeliverable
  phone (e.g. +1 555-01xx, or append a digit to a real number to invalidate it).
  Keep a sanitize script and re-run it whenever new fictional contacts are added.
  EXCEPTION: when the user explicitly wants REAL colleagues to receive the demo
  (to show live clicks/insights), do NOT sanitize those specific contacts —
  mark them clearly (e.g. description "[LiveTarget] DO NOT sanitize") and exclude
  them from the sanitizer. Resolve real colleagues' emails via the org/people
  directory; confirm with the user before any journey that targets them is
  published.

 

═══════════════════════════════════════════════════════════════════════════════
5. CUSTOM COLUMNS (tailor the data model so segments are realistic)
═══════════════════════════════════════════════════════════════════════════════
• Create a publisher (+ prefix) and a solution; pass header
  `MSCRM.SolutionUniqueName: <solution>` on creates so they're exportable.
• Add columns via POST to EntityDefinitions(...)/Attributes with the right
  AttributeMetadata @odata.type (StringAttributeMetadata, MoneyAttributeMetadata,
  IntegerAttributeMetadata, BooleanAttributeMetadata, PicklistAttributeMetadata).
• PUBLISH after adding columns (PublishXml or PublishAllXml) before populating.
• Realistic, segment-friendly columns that worked well (contact + account):
    account: AI maturity (choice), customer tier (choice: Prospect/Pilot/Growth/
             Strategic), current ARR (money).
    contact: buyer persona (choice: Economic Buyer/Technical Champion/
             Practitioner/Influencer), is-decision-maker (bool),
             lead score (int 0–100), monthly product spend (money),
             product-in-use (choice incl. a "None" value for net-new).
• Populate ALL marked rows with consistent values BEFORE building segments that
  filter on them, or segments compute to 0.

 

═══════════════════════════════════════════════════════════════════════════════
6. SEGMENTS  (the #1 source of confusion — read carefully)
═══════════════════════════════════════════════════════════════════════════════
A real-time segment is TWO linked records:
  1) msdynmkt_segmentdefinition — holds the query + refresh config:
       msdynmkt_segmentquery, msdynmkt_staticlistmembers="[]",
       msdynmkt_segmentrefreshintervalminutes (e.g. 60),
       msdynmkt_disablesegmentrefresh=false, statuscode=723270000 (Ready to use)
  2) msdynmkt_segment — the addressable segment:
       msdynmkt_displayname, msdynmkt_description,
       msdynmkt_baseentitylogicalname="contact", msdynmkt_type=11,
       msdynmkt_source=12, msdynmkt_scope=270100000,
       msdynmkt_cdmpartitionprimarykeycolumn="contactid",
       msdynmkt_sourcesegmentuid=<the segmentdefinitionid>   ← THE LINK
PUBLISH / go live:  POST msdynmkt_PublishSegmentDefinition {"SegmentId":<segId>}
  → 204 = success. → 400 returns ResultText JSON naming the parse error+position.

SEGMENT QUERY LANGUAGE (this exact dialect — other operators will 400):
  • Shape: PROFILE(contact).FILTER(<expr>)
  • Join to account:
      PROFILE(contact).FILTER(<contact expr>)
        .RELATEOPTIONAL(contact_customer_accounts, account_1)
        .FILTER(account_1.<field> == <val>)
  • Logical operators: && (AND), || (OR).  ❌ NOT the words AND/OR — that 400s.
  • Equality/compare: ==, >, >=, <, <=.  Booleans: == true.
  • STRING LITERALS USE SINGLE QUOTES: name == 'Microsoft'.
    Double quotes → "Invalid character '\"'". 
  • ❌ CONTAINS(...) and endswith(...) DID NOT PARSE in this dialect — do not
    rely on them. For "all contacts at company X", prefer either the account
    join on name == 'X', or an explicit OR of known email addresses
    (emailaddress1 == 'a@x.com' || emailaddress1 == 'b@x.com' || …). The
    explicit-OR, contact-level form computes almost immediately.
  • Examples that worked:
      Hot leads:   PROFILE(contact).FILTER(incpt_leadscore >= 70)
      Upsell DMs:  PROFILE(contact).FILTER(incpt_isdecisionmaker == true &&
                     incpt_productused == 723720002 && incpt_monthlyapispend > 5000)
      FinServ buyers (join): …FILTER(incpt_persona == 723720000 &&
                     incpt_monthlyapispend > 0).RELATEOPTIONAL(
                     contact_customer_accounts, account_1).FILTER(
                     account_1.industrycode == 16 && account_1.incpt_customertier == 723720003)

SEGMENT STATUS / COMPUTATION:
  • segment statuscode: 1=Active, 6=Computing, 7=ComputedWithWarnings, 3=Error,
    11=Faulted. Member count appears only once Active.
  • LATENCY: new records sync to the segmentation data lake progressively.
    CONTACTS sync within ~minutes; ACCOUNTS (and account-join queries) lag
    longer. A brand-new account can leave a join-based segment "Computing" with
    null members for several minutes. If you need an instantly-correct segment
    (e.g. for a live demo), use the contact-level explicit-OR email form instead
    of an account join — it resolved to the exact members in ~1 minute for us.
  • After publish, poll the segment row's msdynmkt_membercount + statuscode;
    republish if it's stuck and you changed the query.
  • If a user says "the segments are failing," first CHECK statuscode — they're
    often just still Computing, not actually broken. Republish + wait ~60–90s.
• Keep BOTH simple segments (single-field filters) and sophisticated ones
  (multi-signal + account joins). Don't delete the simple ones when adding
  advanced ones unless asked.

 

═══════════════════════════════════════════════════════════════════════════════
7. EMAILS  (msdynmkt_email)  — and the "Ready to send" blocker
═══════════════════════════════════════════════════════════════════════════════
Key fields:
  msdynmkt_subject, msdynmkt_previewtext, msdynmkt_designerhtml (designer
  markup), msdynmkt_emailbody (same HTML), msdynmkt_textpart,
  msdynmkt_automaticallygeneratetextpart=false,
  msdynmkt_emailcontenttype=534120000, msdynmkt_messagedesignation=534120000,
  msdynmkt_emailcontentlanguage=1033, msdynmkt_fromname, msdynmkt_fromemail.
Lookups via @odata.bind (CAPTURE THESE IDS FROM AN EXISTING LIVE EMAIL):
  msdynmkt_senderid → /msdynmkt_brandsenders(<id>)
  msdynmkt_brandprofileid → /msdynmkt_brandprofiles(<id>)
  msdynmkt_purpose → /msdynmkt_purposes(<id>)   (a common value is
     10000000-0000-0000-0000-000000000003, but verify in the org)
  msdynmkt_compliancesettings4 → /msdynmkt_compliancesettings4s(<id>)

DESIGNER HTML requirements (or the designer/validator rejects it):
  • Include the xrm/designer/setting <meta> tags.
  • Wrap editable regions: a container with data-section="true", and blocks with
    data-editorblocktype="Text" | "Button" | "Image".
  • MUST contain the compliance tokens {{CompanyAddress}} and a
    {{PreferenceCenter}} unsubscribe link in the footer.
  • Table-based, inline-styled HTML renders reliably across mail clients.

★ "READY TO SEND" TRANSITION (PATCH statuscode=2)  — the big one:
  statuscode: 1=Draft, 2=Ready to send, 3=Ready to send/editing.
  We chased a generic "Validation returned errors. It is not possible to update
  state to ready to send." The ROOT CAUSE was MISSING FIELDS that the org's
  working email had. Fix = diff your email vs a known-good one and copy:
    • msdynmkt_placeholders  — JSON registering EVERY token. CompanyAddress and
      PreferenceCenter each bind with "source":"LegalDataSource",
      inputs.sourceType.value="Default", outputPath "companyaddress" /
      "preferencescenterurl". Empty/null placeholders → "Placeholders cannot be
      null or empty."
    • msdynmkt_compliancesettings4  (@odata.bind, see above) — REQUIRED.
    • msdynmkt_brandprofiledata  — a small JSON blob; copy it verbatim from a
      working email (capture once, reuse).
    • msdynmkt_replytoemail.
  After adding those four, statuscode=2 succeeded reliably. Save the reusable
  bits (brandprofiledata, replyto, the 4 IDs) to a config file once and reuse
  across all emails.
  To diff quickly: GET your email and a working one, compare which keys are set
  on the good one but null on yours.

PERSONALIZATION TOKENS (dynamic content like "Dear {{FirstName}}"):
  • You CANNOT just type {{contact.firstname}} into the HTML — CIJ validates
    tokens against REGISTERED placeholders. An unregistered token throws
    "Dynamic content contains an invalid property: {{contact.firstname}}."
  • Two reliable paths:
      (a) Let the user insert the token via the designer's Personalization
          picker (Contact → First Name). That registers a placeholder whose KEY
          becomes the token name (e.g. {{FirstName}}) and carries a
          "predefinedPlaceholderId". Then read the email back and COPY that
          placeholder's structure to mirror it elsewhere.
      (b) Register a CdsProfileDataSource placeholder yourself in
          msdynmkt_placeholders keyed by the token name you put in the HTML,
          binding sourceType.value="contact", outputPath="firstname", with a
          sensible defaultValue. Keep the HTML token name IDENTICAL to the key.
  • If a token won't validate, the pragmatic move (which the user often prefers)
    is to keep ONLY the working token (e.g. {{FirstName}}) and replace other
    {{contact.*}} literals with neutral copy, then go Ready to send. Always
    strip every unregistered {{…}} before publishing.
  • Personalized subject lines work too (same token, e.g. "{{FirstName}}, …").
• Create a healthy mix: some emails Ready to send, some left Draft, each
  targeting a different product/segment angle.

 

═══════════════════════════════════════════════════════════════════════════════
8. CONTENT BLOCKS  (msdynmkt_fragment)  — reusable drag-in chunks
═══════════════════════════════════════════════════════════════════════════════
• Writable fields: msdynmkt_name, msdynmkt_designerhtml, msdynmkt_finalizedhtml,
  msdynmkt_previewhtml (all three HTML fields are ApplicationRequired — set them
  to the same markup), msdynmkt_contenttype (1=Static, 2=Dynamic preview),
  msdynmkt_protected=false.
• Wrap the block HTML in a minimal designer doc shell (DOCTYPE + the
  xrm/designer/setting type meta) and use the same data-section /
  data-editorblocktype conventions as emails.
• PUBLISH a content block the same way as emails: PATCH statuscode=2
  (1=Draft, 2=Ready to send, 3=Ready/editing, 100=Inactive). Published blocks
  become available to drag into emails.
• Good set: Branded Header, Compliant Footer (with the two compliance tokens),
  Primary CTA Button, Product/Feature Card.

 

═══════════════════════════════════════════════════════════════════════════════
9. EMAIL TEMPLATES  (msdynmkt_emailtemplate)  — journey starting points
═══════════════════════════════════════════════════════════════════════════════
• Like emails but they're reusable authoring starting points. Fields mirror
  email: msdynmkt_name, msdynmkt_subject, msdynmkt_previewtext,
  msdynmkt_designerhtml, msdynmkt_emailbody, msdynmkt_textpart,
  msdynmkt_category (0=Gallery, 1=Custom templates → use 1),
  msdynmkt_contenttype=534120000, msdynmkt_messagedesignation=534120000,
  msdynmkt_language=1033.
• Use neutral placeholder copy ([Product Name], [Event Name], [Key benefit]) so
  marketers fill them in. Templates don't need the Ready-to-send transition.

 

═══════════════════════════════════════════════════════════════════════════════
10. SMS / TEXT MESSAGES  (msdynmkt_sms)
═══════════════════════════════════════════════════════════════════════════════
• Fields: msdynmkt_name, msdynmkt_text, msdynmkt_designertext (set both to the
  message), msdynmkt_messagedesignation=534120000, msdynmkt_placeholders="{}".
• Lookups: msdynmkt_compliance → /msdynmkt_compliancesettings4s(<id>),
  msdynmkt_purpose → /msdynmkt_purposes(<id>).
• Always include a compliant opt-out ("Reply STOP to opt out") and keep it short.
• Go live: PATCH statuscode=2 (worked reliably for SMS).
• Remember sanitized phones make SMS undeliverable by design — fine for demos.

 

═══════════════════════════════════════════════════════════════════════════════
11. PUSH NOTIFICATIONS  (msdynmkt_pushnotification)
═══════════════════════════════════════════════════════════════════════════════
• Fields: msdynmkt_name, msdynmkt_title, msdynmkt_message,
  msdynmkt_onclickbehavior (534120000=Open the app, 534120001=Open in browser,
  534120002=Open Customer Voice survey), msdynmkt_placeholders="{}".
• Same compliance/purpose lookups as SMS.
• ⚠️ Push CANNOT go fully live without a registered mobile app / push channel,
  which demo orgs usually lack — so leave push notifications as Draft
  (statuscode=1). The org's own sample push is typically Draft for this reason.
  Set this expectation with the user instead of fighting the validator.

 

═══════════════════════════════════════════════════════════════════════════════
12. JOURNEYS  (msdynmkt_journey)  — multi-touchpoint, segment-triggered
═══════════════════════════════════════════════════════════════════════════════
• The whole flow lives in msdynmkt_journeyjson (a big JSON string). Also set
  msdynmkt_name and msdynmkt_triggertype=0. New journeys are Draft
  (statecode=0, statuscode=1) — leave them Draft unless the user says launch.
• BEST PRACTICE: dump a working "scheduled" journey's JSON from the org and use
  it as your structural template; then swap in your segment + email IDs.
• Top-level keys: type(1), typeName("scheduled"), exitCriteria{exitEvents:[]},
  contentVersion("1.0.0.0"), name, targetEntityLogicalNames(["contact"]),
  goal{…}, trigger{…}, actions{…}, uiMetadata{}, journeyUiFeatureFlags{…},
  timeZoneCode, timeZoneWindowsName.
• trigger: {"type":"OneTime","audience":"<segmentId>","parameters":
  {"startTime":""},"exclusionSegments":[]}   ← audience = the segment GUID.
• actions is a DICT keyed by GUID. Wire ordering via each action's
  "runAfter": {"<prevActionId>": {"result":"Success"}}.
  - Email action: type "Email", parameters include contentId=<emailId>,
    purposeId, messageDesignation=534120000, complianceSettingsId,
    contentReadyToSend=true, recipient bound to CdsProfileDataSource
    outputPath "emailaddress1", and placeholderBindings (+ …Original) for
    CompanyAddress/PreferenceCenter (LegalDataSource, same shape as in emails),
    quietTimeSettingsSelectedOption="ApplyDefaultQuietTime".
  - Delay action: type "Delay", parameters {"type":"Wait","count":N,"unit":3}
    (unit 3 = days).
  - Branch action: type "Event", eventType=2, eventName=
    "msdynmkt_emaillinkclicked", waitForType=0, timeoutParameters{count,unit:3},
    with nested succeedActions (e.g. follow-up Email → Delay → CreateRecord lead)
    and timeoutActions (e.g. a nurture Email). resumeCriteria{criteria:{}}.
  - CreateRecord (lead) action: entityName "lead", properties as binding
    objects — ConstantValueDataSource for static values (subject, etc.),
    CdsProfileDataSource for contact-sourced fields (firstname, lastname,
    emailaddress1→ map to lead, ownerid as lookup, contactid→parentcontactid).
• Generate fresh GUIDs (uuid4) for every action id. Mirror the placeholder /
  recipient binding objects exactly from a working journey or from the email
  section above.
• A reliable demo pattern: Email1 → Delay → "If link clicked?"
    ├ clicked  → Email2 → Delay → Create Lead   (shows conversion + insights)
    └ timeout  → nurture Email2.
• For a LIVE-CLICKS demo: target a segment of REAL recipients, use a Ready
  email, leave the journey Draft, and let the USER click Publish so they own the
  send. Publishing sends real messages and produces real open/click/insights.

 

═══════════════════════════════════════════════════════════════════════════════
13. WORKFLOW WHEN I ASK FOR SOMETHING
═══════════════════════════════════════════════════════════════════════════════
1. Inspect existing assets of that type (schema + a known-good live example).
2. Build via dv.py (POST with Prefer: return=representation). Save reusable
   scripts under scripts/ with clear names (create_segments.py, create_emails.py,
   create_journeys.py, create_push_sms.py, sanitize_contacts.py, …) and persist
   created GUIDs to small JSON state files for later wiring.
3. Transition to live where applicable (segments: PublishSegmentDefinition;
   emails/blocks/sms: statuscode=2; push: leave Draft; journeys: leave Draft).
4. VERIFY by reading statecode/statuscode/membercount back. Don't declare done
   until confirmed.
5. On any failure, read the full error body and fix the named field — for
   "ready to send" issues, diff against a working record.
6. Keep a todo list and update it as items complete.

 

═══════════════════════════════════════════════════════════════════════════════
14. REUSABLE CONFIG TO CAPTURE ONCE PER ORG
═══════════════════════════════════════════════════════════════════════════════
From an existing live email/sms in the org, capture and reuse everywhere:
  • senderId, brandProfileId, purposeId, complianceSettings4 id
  • fromEmail, replyToEmail
  • brandprofiledata JSON blob
  • the CompanyAddress / PreferenceCenter placeholder binding objects
  • the org's timeZoneCode + timeZoneWindowsName (for journey JSON)
Store them in scripts/email_config.json (or similar) so every create script
pulls from one place.

 

═══════════════════════════════════════════════════════════════════════════════
START HERE
═══════════════════════════════════════════════════════════════════════════════
1. Run `pac auth list` / `pac org who`; confirm the right org (section 1).
2. Stand up scripts/dv.py with the URL-encoding + token-refresh rules.
3. Detect msdynmkt_* (real-time) vs msdyncrm_* (outbound) and capture the
   reusable config IDs (section 14) from a working email.
4. Ask me what to build first (contacts/accounts, segments, emails, journeys,
   SMS, push, content blocks, templates) and follow the per-asset rules above.
Always sanitize fictional contacts before any journey can send (section 4),
and never publish a journey that targets real people without my explicit OK.
