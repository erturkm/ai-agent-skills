# The widget

A React app, bundled to **one self-contained HTML file**, served as an MCP resource and
rendered by Copilot in a sandboxed iframe with `window.openai` injected.

## Build config — must inline everything

```ts
// widget/vite.config.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: 'dist',
    assetsInlineLimit: 100000000,     // inline every asset regardless of size
    cssCodeSplit: false,
    reportCompressedSize: false,
    rollupOptions: { output: { inlineDynamicImports: true } },
  },
});
```

The iframe has no origin to fetch sibling assets from. **Any external `<script src>` or
`<link href>` produces a blank widget.** One file, no exceptions.

Build script copies the bundle where the server expects it:

```json
"build": "vite build && node -e \"const fs=require('fs');fs.mkdirSync('../server/public',{recursive:true});fs.copyFileSync('dist/index.html','dist/widget.html');fs.copyFileSync('dist/index.html','../server/public/widget.html');console.log('widget.html -> server/public')\""
```

Keep dependencies to React + ReactDOM. A component library will blow the bundle up and most
of it cannot style itself correctly inside the sandbox anyway — hand-rolled CSS matching the
Fluent/D365 palette looks better and loads instantly.

---

## The host bridge (`src/bridge.ts`)

**Capability-detect everything.** The widget must still render in a plain browser with no host
— that is how you preview and screenshot it.

```ts
declare global {
  interface Window {
    openai?: {
      toolInput?: unknown;
      toolOutput?: unknown;
      widgetState?: unknown;
      displayMode?: string;
      theme?: string;
      locale?: string;
      setWidgetState?: (s: unknown) => void | Promise<void>;
      callTool?: (name: string, args: unknown) => Promise<any>;
      sendFollowUpMessage?: (a: { prompt: string }) => void | Promise<void>;
      requestDisplayMode?: (a: { mode: string }) => void | Promise<void>;
      notifyIntrinsicHeight?: (h: number) => void;
      openExternal?: (a: { href: string }) => void;
      setOpenInAppUrl?: (url: string) => void;
    };
  }
}

const oai = () => (typeof window !== 'undefined' ? window.openai : undefined);
export const hostAvailable = () => !!oai();
```

### Reading tool output

```ts
export function readToolOutput(): Snapshot | null {
  const o = oai()?.toolOutput as any;
  if (!o) return null;
  if (o.structuredContent) return o.structuredContent as Snapshot;   // normal shape
  if (o.account) return o as Snapshot;                                // already unwrapped
  return null;
}

/** Subscribe to host-pushed updates (new tool results, theme, display mode). */
export function useHostSnapshot(): [Snapshot | null, (s: Snapshot) => void] {
  const [snap, setSnap] = useState<Snapshot | null>(() => readToolOutput());
  useEffect(() => {
    const onSet = () => { const next = readToolOutput(); if (next) setSnap(next); };
    const events = ['openai:set_globals', 'openai:tool_response', 'openai:tool_output'];
    events.forEach((e) => window.addEventListener(e, onSet as EventListener));
    return () => events.forEach((e) => window.removeEventListener(e, onSet as EventListener));
  }, []);
  return [snap, setSnap];
}
```

Listen to **all three** event names. Which one fires depends on host version, and the payload
shape varies — tolerate both.

### Calling tools back from the widget

```ts
export async function callTool(name: string, args: unknown): Promise<any> {
  const fn = oai()?.callTool;
  if (!fn) throw new Error('Tool calling is not available in this host.');
  return fn(name, args);
}

/** Call a tool and fold a fresh snapshot back into the UI if one comes back. */
export async function callToolAndRefresh(
  name: string, args: unknown, apply: (s: Snapshot) => void,
): Promise<string> {
  const res = await callTool(name, args);
  const sc = res?.structuredContent ?? res?.result?.structuredContent;   // both shapes
  if (sc?.account) apply(sc as Snapshot);
  return res?.content?.find?.((c: any) => c.type === 'text')?.text
      ?? res?.result?.content?.find?.((c: any) => c.type === 'text')?.text
      ?? 'Done.';
}
```

This is what makes the widget *interactive* rather than a static card — a button in the UI can
write to Dataverse and refresh itself without a chat turn.

### Persistent state, theme, display mode, height

```ts
/** Survives re-renders and conversation scrollback. */
export function usePersistentState<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const ws = oai()?.widgetState as any;
    return ws && key in ws ? (ws[key] as T) : initial;
  });
  const set = useCallback((v: T) => {
    setValue(v);
    const ws = (oai()?.widgetState as any) ?? {};
    oai()?.setWidgetState?.({ ...ws, [key]: v });
  }, [key]);
  return [value, set];
}

export function useTheme(): 'light' | 'dark' {
  const read = (): 'light' | 'dark' => {
    const t = oai()?.theme;
    if (t === 'dark' || t === 'light') return t;
    return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  };
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    const on = () => setTheme(read());
    window.addEventListener('openai:set_globals', on as EventListener);
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    mq?.addEventListener?.('change', on);
    return () => {
      window.removeEventListener('openai:set_globals', on as EventListener);
      mq?.removeEventListener?.('change', on);
    };
  }, []);
  return theme;
}

/** Keep the inline iframe sized to the content — without this it clips. */
export function useAutoHeight(ref: React.RefObject<HTMLElement | null>, deps: unknown[]) {
  useEffect(() => {
    const notify = oai()?.notifyIntrinsicHeight;
    if (!notify || !ref.current) return;
    const report = () => { const h = ref.current?.scrollHeight ?? 0; if (h > 0) notify(h); };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, deps);
}

export const sendFollowUp = (prompt: string) => oai()?.sendFollowUpMessage?.({ prompt });
export const requestFullscreen = () => oai()?.requestDisplayMode?.({ mode: 'fullscreen' });
export const setOpenInAppUrl = (url: string) => oai()?.setOpenInAppUrl?.(url);
export function openExternal(href: string) {
  const fn = oai()?.openExternal;
  if (fn) fn({ href }); else window.open(href, '_blank', 'noopener');
}
```

**Always support dark mode.** Copilot follows the user's theme and a light-only widget on a
dark chat looks broken. Drive it with CSS custom properties and a `data-theme` attribute.

**`useAutoHeight` is not optional** — inline widgets default to a short fixed height and your
card will be cut off mid-table.

---

## App root: reconciling two sources of state

The widget receives state from two places — the host (a new tool result) and its own
`callTool` responses. They can arrive out of order. Resolve with the server's `renderedAt`
stamp:

```tsx
function newerOf(a: Snapshot | null, b: Snapshot | null): Snapshot | null {
  if (!a) return b;
  if (!b) return a;
  return (b.renderedAt ?? '') > (a.renderedAt ?? '') ? b : a;
}

export default function App() {
  const [hostSnap] = useHostSnapshot();
  const [local, setLocal] = useState<Snapshot | null>(null);
  const snap = newerOf(local, hostSnap);

  // Every fresh host payload supersedes optimistic local state and re-seeds the
  // active step, so "update the narrative" re-renders on step 2 rather than
  // leaving the user parked wherever they last were.
  const seededRef = useRef<string | null>(null);
  useEffect(() => {
    if (!hostSnap) return;
    const stamp = hostSnap.renderedAt ?? '__initial__';
    if (seededRef.current === stamp) return;
    seededRef.current = stamp;
    setLocal(null);
    if (hostSnap.activeStep) setStep(hostSnap.activeStep);
  }, [hostSnap?.renderedAt, hostSnap]);
```

Without this the widget appears to freeze: the first payload wins forever and every subsequent
tool call seems to do nothing.

### Explicit refresh

Offer a refresh button that goes **back to Dataverse** rather than patching local state, so it
also picks up edits made in Dynamics or by a colleague outside the conversation:

```tsx
const res = await callTool('refresh_workspace', { account, plan, step });
const sc = res?.structuredContent ?? res?.result?.structuredContent;
if (sc?.account) setLocal({ ...(sc as Snapshot), activeStep: step });  // keep the user's step
```

Note `activeStep: step` — refreshing must not move the user.

---

## Making it look like Dynamics 365

What sells the demo is that it looks native. Build a small shell module:

- **`AppBar`** — waffle, app name, search, settings cluster
- **`RecordHeader`** — record title, key fields in a row, record-type chip
- **`CommandBar`** — `+ New`, Save, Refresh, Assign, Flow, overflow `…`
- **`ProcessBar`** — the BPF stage chevrons, with the active stage expanded
- **`TabStrip`** — General / Related / etc.

Palette: D365 blue `#0F6CBD`, neutral greys, 4px radii, 12–14px type, generous whitespace.
Use the `accentColor` from the Teams manifest so chat chrome and widget agree.

**Deep-link out to the real app** so the agent composes with Dynamics rather than replacing it:

```tsx
useEffect(() => {
  const url = snap?.links?.plan ?? snap?.links?.account;
  if (url) setOpenInAppUrl(url);          // wires the host's "open in app" affordance
}, [snap?.links?.plan, snap?.links?.account]);
```

Build the URL server-side:
`${DV_URL}/main.aspx?appid=${AP_APP_ID}&pagetype=entityrecord&etn=${table}&id=${guid}`

---

## Embedding the model-driven app itself: don't

Iframing a Dynamics 365 or canvas app URL inside the widget **does not work**. Dataverse sends
`X-Frame-Options`/CSP that the Copilot sandbox cannot satisfy, and the host does not currently
honour `openai/frameDomains`. The frame renders blank or refuses to load.

Build the UI natively in the widget against the same data, and use `setOpenInAppUrl` /
`openExternal` to hand off to the real app in a new tab when the user wants the full surface.

---

## Preview harness — look at it before you ship

Accessibility snapshots do not catch cosmetic defects. Build static preview pages from captured
fixtures and screenshot them.

1. **Capture real payloads** once, through the live server, into `scripts/fixtures/*.json`.
2. **`scripts/preview.mjs`** writes `preview/*.html`: the built bundle with
   `window.openai = { toolOutput: { structuredContent: FIXTURE }, theme }` injected before the
   app script. Emit a light and a dark page per card.
3. Serve and screenshot:

```bash
node scripts/preview.mjs && python3 -m http.server 8899 -d preview
# then screenshot every page, light and dark, and LOOK at them
```

Defects this catches that nothing else does: an emptied field leaving a stray "—" chip,
numbers overflowing their column, a dark-mode contrast failure, a doubled currency prefix
(`AED AED 60.0B`) buried in prose.

**Dump prose untruncated when checking it.** Truncated output has hidden a second instance of
exactly the same bug on the line below.
