# Demo safety

Demo orgs are shared. Your agent writes to Dataverse. Without the controls below, one rehearsal
quietly corrupts a colleague's demo data and nobody notices until they are on stage.

**Build the journal before the first write tool.** Retrofitting it cannot undo the writes you
have already made.

---

## 1. The write journal

Every write is appended to a JSONL journal with its prior value, so the whole demo is revertible
in one tool call.

```ts
export interface JournalEntry {
  ts: string;
  op: 'create' | 'update';
  entitySet: string;
  rowId: string;
  label?: string;                        // human label, so list_demo_changes reads nicely
  before?: Record<string, unknown>;      // for updates: values as they were BEFORE
  after?: Record<string, unknown>;
  reverted?: boolean;
}
```

Two classes of row, handled differently:

- **Agent-owned** — created by this agent. Reverting **deletes** them.
- **Protected** — pre-existed. Reverting **restores** the journalled `before` values.

Ownership is derived from Dataverse `createdby`, **not** from the journal. That matters: the
guard then survives a journal loss or a container restart.

### Wrap every write

Two entry points: `recordCreate(entitySet, rowId, label)` after a POST, and `guardedUpdate`
for every PATCH. `guardedUpdate` is the **only** path that may touch a pre-existing row.

```ts
export async function guardedUpdate(
  entitySet: string, rowId: string, fields: Record<string, unknown>, label?: string,
): Promise<void> {
  const keys = Object.keys(fields);
  let before: Record<string, unknown> | undefined;

  if (protectExisting() && keys.length) {
    // Lookups are WRITTEN as `Nav@odata.bind` but must be READ as `_nav_value`.
    const reads = keys.map((k) => {
      const m = /^(.+)@odata\.bind$/.exec(k);
      return m ? { key: k, select: `_${m[1].toLowerCase()}_value`, nav: m[1] }
               : { key: k, select: k };
    });
    try {
      const cur = await dv<any>(
        `${entitySet}(${rowId})?$select=${reads.map((r) => r.select).join(',')}`);
      before = {};
      for (const r of reads) {
        const v = cur?.[r.select] ?? null;
        // Re-express the prior lookup as a bind so revert can write it back.
        before[r.key] = r.nav ? (v ? `/${bindSetFor(r.nav)}(${v})` : null) : v;
      }
    } catch {
      // If we cannot read the prior state we must not silently overwrite it.
      throw new Error(
        `Refusing to update ${entitySet}(${rowId}): could not read its current values to ` +
        `make the change revertible. Set AP_PROTECT_EXISTING=false to override.`);
    }
  }

  await dv(`${entitySet}(${rowId})`, { method: 'PATCH', body: fields });
  append({ ts: new Date().toISOString(), op: 'update', entitySet, rowId, label,
           before, after: fields });
}
```

Three things here are load-bearing:

- **Read the prior value before the write**, selecting exactly the fields you are about to
  change. A revert that restores fields you never touched is its own kind of damage.
- **Lookup asymmetry.** You write `fsi_Customer@odata.bind: "/accounts(guid)"` but you read
  `_fsi_customer_value`. Capture the read form and re-express it as a bind, or revert silently
  fails to restore relationships.
- **Fail closed.** If the prior state can't be read, *refuse the write*. An unrevertible change
  is worse than a failed one.

### Storage

```ts
const JOURNAL_PATH = process.env.AP_JOURNAL_PATH
  ?? join(process.cwd(), '.demo-journal', 'writes.jsonl');
```

On Container Apps use `/tmp/journal.jsonl`. It is per-revision and lost on restart — acceptable,
because ownership comes from Dataverse. If you need it durable, write to blob storage with the
same service principal (`Storage Blob Data Contributor` on the account).

Parse tolerantly — a truncated final line must not take down the server:

```ts
function parseJsonl(text: string): JournalEntry[] {
  return text.split('\n').filter((l) => l.trim())
    .map((l) => { try { return JSON.parse(l) as JournalEntry; } catch { return null; } })
    .filter(Boolean) as JournalEntry[];
}
```

**Single replica only.** The journal is in-process; a second replica would not see the first
one's pending changes. Pin `minReplicas: maxReplicas: 1`.

---

## 2. The read-only guard

Pre-existing records are reference data. The agent may read them but must write only to records
it created in this conversation.

```ts
export const protectExisting = (): boolean =>
  (process.env.AP_PROTECT_EXISTING ?? 'true').toLowerCase() !== 'false';
```

Protection is **on unless explicitly disabled** — the safe default survives a missing env var.

Ownership is checked against the **S2S application user's `systemuser` id**, obtained from
`WhoAmI` — *not* the app registration's client id. Every row the agent creates is created by
that application user; pre-existing demo data was created by real users.

```ts
let appUserId: string | null = null;

/** The systemuser id of the S2S application user this server authenticates as. */
export async function getAppUserId(): Promise<string> {
  if (appUserId) return appUserId;
  const who = await dv<{ UserId: string }>('WhoAmI');
  appUserId = String(who.UserId).toLowerCase();
  return appUserId;
}

/**
 * Durable ownership check. The in-memory journal is lost when the container
 * restarts, but `createdby` is not. Fails *closed*: if we can't prove we
 * created the row, it is treated as protected.
 */
export async function isAgentCreated(entitySet: string, rowId: string): Promise<boolean> {
  if (isAgentOwned(entitySet, rowId)) return true;        // fast path: the journal
  try {
    const me = await getAppUserId();
    const row = await dv<any>(`${entitySet}(${rowId})?$select=_createdby_value`);
    return String(row?._createdby_value ?? '').toLowerCase() === me;
  } catch {
    return false;                                          // fail closed
  }
}
```

Journal first (cheap), Dataverse second (durable), `false` on any error. That ordering is what
keeps the guard correct across container restarts *and* fast in the common case.

Surface the refusal in the agent instructions so the model handles it gracefully rather than
retrying:

> Pre-existing account plans in this environment are demo reference data and **must never be
> modified**. You may read them, but all writes must go to a plan that you created in this
> conversation. If a write is refused because the plan is protected, explain that and offer to
> create a fresh plan instead. **Never try to work around the guard.**

### Shared rows are the hard case

Some journeys genuinely must edit *shared, account-level* rows that pre-date the agent (share of
wallet, cross-sell, stakeholders). Blocking those guts the demo. The resolution is not to block
them but to **journal them with their prior values** so they are restorable. Protection applies
to the parent record; shared children are journalled.

---

## 3. The two presenter tools

Give the presenter a way to see and undo everything, from chat.

```ts
server.registerTool('list_demo_changes', {
  title: 'List what this agent has changed',
  description: 'Show every Dataverse record this agent has created or modified, with prior values.',
  annotations: { readOnlyHint: true },
}, async () => { /* read journal, format pending entries */ });

server.registerTool('revert_demo_changes', {
  title: 'Undo everything this agent has written',
  description:
    'Roll Dataverse back to the state it was in before this agent made any changes: restores ' +
    'modified fields to their previous values and deletes records the agent created. Use after ' +
    'a demo to leave the environment clean. Confirm with the user first.',
  inputSchema: { deleteCreated: z.boolean().optional() },
  annotations: { readOnlyHint: false, idempotentHint: true },
}, async ({ deleteCreated }) => {
  const r = await journal.revertAll({ deleteCreated: deleteCreated ?? true });
  // report restored / deleted counts AND any failures explicitly
});

```

**Report partial failure loudly.** A revert that restored 8 of 10 rows and said "done" is worse
than one that failed outright:

```
Reverted: 8 field restore(s), 2 record deletion(s).
⚠️ 1 failed:
- fsi_accountplans: 403 Forbidden
```

Add a conversation starter for it — *"What have you changed in Dataverse so far? Show me, then
revert everything."* — so cleanup is one click at the end of a demo.

---

## 4. Display-name masking for public stages

When a demo uses a real customer's data but the name cannot appear on a conference screen.

**Keep the lookups real; mask only at the point data becomes visible.** Fetching live market
data for the real company is the whole value of the integration. Substitute the display name on
the way out.

```ts
/** Inert unless AP_MASK_CONFIG is set — so the unmasked agent is byte-identical. */
export function maskerFor(accountName: string): Masker | null { … }
```

Three properties that matter:

1. **Keyed on the *Dataverse account display name*, never the real company.** The masked agent
   asks for "Northwind Gas"; the masker maps that to the real company for the upstream call and
   scrubs the real name out of the response.
2. **Inert by default.** No `AP_MASK_CONFIG` ⇒ `maskerFor()` returns `null` ⇒ the original agent
   is unaffected. Assert this in tests.
3. **`scrubList` fails closed.** Free text (news headlines, analyst notes) can name a company
   the substitution map has never seen. Items still matching a blocked term *after* scrubbing
   are **dropped entirely**. Losing a headline is recoverable; showing the real name on stage is not.

Also suppress structural identifiers, not just the name — tickers/RICs, exchange identifiers,
ISINs, permIds. A RIC like `R:CONTOSOENERGY.XX` names the company as surely as the name does.

```ts
if (mask.hideTicker) {
  if (out.entity)  out.entity  = { ...out.entity, ric: undefined, permId: undefined };
  if (out.listing) out.listing = { ...out.listing, ric: undefined, primaryRic: undefined, isin: undefined };
}
```

**Conditionally render, don't blank.** A suppressed field left in the markup renders as a stray
"—" chip. `{entity.ric ? <span…> : null}` — and verify on a *screenshot*, not a DOM snapshot.

### Leak scan — automate it

Never eyeball this. Scan every tool's full response for every blocked term plus the identifier
fields, and run it before every rehearsal:

```python
BLOCKED = ["RealCo", "RealCo Gas", "REALCO", "R:REALCO.AD", …]
for tool in ("get_overview", "get_financials", "get_news"):
    blob = json.dumps(call(tool, {"company": "Northwind Gas"})).lower()
    hits = [t for t in BLOCKED if t.lower() in blob]
    assert not hits, f"{tool}: LEAKED {hits}"
```

Exit non-zero = do not present. Keep one source of truth for the name map (a single
`names.py`), and generate `AP_MASK_CONFIG` from it — hand-maintaining both halves guarantees
they drift.

### Seeding the masked account

Copy the real account's rows to the masked account and scrub the copies. **Never modify the
source rows.** Assert it afterwards rather than trusting it:

```python
before = snapshot_of(REAL_ACCOUNT)
seed_masked_account()
assert snapshot_of(REAL_ACCOUNT) == before, "source data was modified"
```

---

## 5. Pre-demo checklist

```bash
curl -fsS "$HEALTH_URL"                   # server up
python3 tests/test_tools.py               # tool count + live data
python3 tests/test_guard.py               # guards hold, revert restores
python3 scripts/leakscan.py               # masking, if used — exit 1 ⇒ do not present
python3 tests/test_agent_packages.py      # rendered packages valid, agents separated
```

Then run the journey in Copilot and **look at every card** in the theme you will present in.
