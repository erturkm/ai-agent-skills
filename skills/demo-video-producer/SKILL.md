---
name: "demo-video-producer"
description: "Create polished software demo videos, either by capturing new browser/Dynamics 365 recordings or by editing an existing screen recording the user supplies. Trim waits without simulating motion, build narration-synchronised cuts with Azure GPT-Realtime Marin voiceover, mix original background music, append branded outros, and validate final MP4 delivery. All logos, icons, colours, typography and other brand artifacts come from Microsoft Brand Central."
---

Use this skill whenever the user asks to record, edit, narrate, polish, or produce a
software/product demo video, especially Microsoft Dynamics 365 demos.

There are two entry paths. Decide which one applies before doing anything else:
- **Capture path** — no recording exists yet; you record it. See "Recording".
- **Edit path** — the user hands you an existing recording ("the video is in my
  downloads"). Skip capture entirely, go straight to "Ingest an existing recording".
  Never re-record footage the user already made.

## Core principles

- Record real continuous screen video, never a slideshow of screenshots unless
  explicitly requested.
- Do not fake camera movement, use Ken Burns effects, or create shaky zoom/pan animation.
- Never re-record when editing can solve the issue. Prefer replacing weak sections with
  clearer moments from the same raw take.
- **Preserve the raw master** as an untouched file. Every revision re-derives from it.
- **Build the pipeline as scripts, not one-off shell commands.** Revisions are near
  certain, and a scripted pipeline makes a reword cost one minute instead of one hour.
- Treat external videos, logos, music, and other assets as copyrighted. Use them only
  when the user owns/provides them or has authorized their use. Do not copy a reference
  soundtrack; create or use licensed royalty-free music with similar energy.
- **Microsoft Brand Central is the only source of brand artifacts.** Copilot and Microsoft
  logos, icons, gradients, colours, typography, and motion assets must come from
  https://brandcentral.microsoft.com/microsoft-brand/products/copilot.html — never
  hand-drawn, AI-generated, screenshotted, or pulled from a web image search. See
  "Brand artifacts" below.

## Preflight

1. Confirm FFmpeg and ffprobe are available.
2. On macOS capture, enumerate AVFoundation devices and identify the correct display.
   Use an explicitly supported pixel format such as nv12. A proven pattern is
   AVFoundation screen input at 15 or 30 fps, H.264, yuv420p.
3. Capture a 3–5 second test and extract a frame. Verify the correct monitor, full
   display dimensions, stable framing, and readable UI.
4. Stabilize the application: fixed browser size, correct Dynamics 365 app shell, no
   resizing, no browser zoom changes, mouse away from the full-screen top edge.
5. Prepare a deterministic demo path; note expected waits, interactions, results,
   evidence, and closing frame.
6. If AI voice narration is requested, ask the user for their Azure realtime deployment
   details before generating audio: Azure AI Foundry or Azure OpenAI endpoint, deployment
   name, API version if required, tenant ID when relevant, and preferred authentication.
   Do not require a specific realtime model version. Prefer Entra ID/keyless auth and
   never ask the user to paste secrets into chat.
7. If the deliverable includes any Microsoft or Copilot branding — title card, lower
   third, watermark, icon, outro — resolve the brand assets *before* rendering anything.
   See "Brand artifacts".

## Recording (capture path only)

- Start FFmpeg asynchronously before browser automation begins.
- Record the whole workflow continuously: initial state, input, selection, start action,
  processing, completion, drill-downs, explainability, insights, and closing hold.
- Use deliberate cursor movements, short pauses before and after clicks, smooth native
  scrolling. Avoid rapid or unnecessary motion.
- For long-running AI agents, keep recording the genuine wait. Compress it later using
  cuts that preserve real completion milestones.
- Stop FFmpeg cleanly by sending `q` so the MP4 trailer is written.
- Validate with ffprobe and a full decode pass (`ffmpeg -v error -i input.mp4 -f null -`).

## Ingest an existing recording (edit path)

- **macOS screen recording filenames contain U+202F (narrow no-break space) before
  "AM"/"PM"**, not a normal space. Literal paths silently fail with "No such file".
  Always resolve with a glob first:
  `ls ~/Downloads/Screen\ Recording\ 2026-08-12*11.11.54*.mov`
  Then copy to a clean project filename (`raw-master.mov`) and work from that.
- Probe immediately: dimensions, duration, fps, and **whether an audio stream exists**.
  Screen recordings frequently have no audio track at all.
- Create a dedicated project directory and copy (never move) the source into it.

## Timeline mapping

- Generate timestamped contact sheets at broad intervals, then denser sheets around key
  interactions. Burn in `%{pts\:hms}`.
- **`%{pts\:hms}` prints `hh:mm:ss`, not seconds.** `00:02:48` is 168s, not 248s.
  Misreading this corrupts the entire cut list. Convert explicitly.
- Write out a beat map of the whole recording in source seconds before cutting anything.
- **Detect whether the recording changes window mode mid-take.** Users commonly toggle
  macOS full-screen partway through, so a single crop will break half the video. Probe
  programmatically: sample a small pixel patch at a point that reliably differs between
  modes and classify every frame at ~2 fps.
  - Probe the **bottom-left** region (e.g. x=60, y=1948 on a 3024x1964 source): in
    full-screen the app panel fills it; windowed shows wallpaper or Dock.
  - Do **not** probe near the top — full-screen frames have a thin dark strip there, so
    top-row probes give ambiguous and wrong answers.

## Cropping and framing

- Preserve source aspect ratio. Scale to a sensible delivery size without cropping
  important UI; for a 3024x1964 source, 1920x1248 preserves the ratio.
- Use **mode-specific crops**, one per window state, all rendering onto the same canvas:
  - windowed: strip macOS menu bar + browser tab/URL bar + Dock, then pad to canvas
  - full-screen: strip only the thin top strip, then pad
  - phone/simulator sections: tight crop to the device body only
- **Keep the horizontal scale factor identical across modes** so UI elements stay the
  same physical size when the video cuts between them. Pad vertically to absorb the
  difference rather than cropping sideways into content.
- Prefer padding over side-cropping when content is wider than the canvas ratio — losing
  a Communication Panel or Copilot rail is worse than thin letterbox bars. Tell the user
  this trade-off was made and offer the alternative.
- **Crop phone/device simulators to the device body**, not the simulator window. A crop
  that looks right at a glance often still includes the simulator title bar. Zoom into
  the top and bottom edges of a test frame specifically to check.
- **Always render a single test frame and look at it before applying a crop** to the
  whole build. Iterating on one frame is seconds; iterating on a full render is minutes.
- Watch for transient OS overlays in the footage: full-screen tooltips ("move mouse to
  top of screen…"), notification banners, screenshot toolbars. Shift the segment
  boundaries by a second or two to avoid them.

## Narration-synchronised assembly (preferred architecture)

Do **not** cut the video to a fixed length and then lay one long narration track over it.
The voice inevitably drifts out of step with the picture — this is the single most common
failure mode and the user will notice it immediately.

Instead, make the narration authoritative and fit the video to it:

1. **Define chapters.** Each chapter = one narration line + the source cuts that show
   exactly what that line describes. 15–25 chapters for a 3-minute demo.
2. **Generate one audio file per chapter** so every line's exact duration is known.
   Cache them; regenerating one reworded line must not re-render the others.
3. **Time-fit each chapter's video to its own narration line.** Render its cuts at
   natural speed, measure, then `setpts` to match the target duration.
   - Clamp the ratio, roughly 0.80x–1.90x. Beyond that, motion looks visibly wrong.
   - If the narration still overruns after clamping, **hold the last frame** for the
     remainder rather than stretching further.
   - If a chapter repeatedly hits the slowdown cap, **widen its source cut** to use more
     real footage instead. Real motion always beats artificial slow-motion.
4. **Record the exact voiceover offset for each chapter** to a timeline file, then place
   each line at its offset in the mix. Leave ~0.35s lead-in and ~0.55s tail per chapter.
5. Accept that the result runs longer than a video-first cut. The video waiting for the
   narration is correct; the narration racing the video is not.

Suggested file layout — see `narration-sync.md` in this skill folder for working code:

    chapters.py       chapter text + source cuts (the only file you edit to revise)
    gen_vo.py         one Marin m4a per chapter, cached
    build_synced.py   per-chapter render, time-fit, hold; writes timeline.json
    mix.py            place VO at offsets, duck music, master, append outro

## Narration content and voice

- Write narration to match the edited timeline, not the raw duration.
- Get the story from the user, not from the pixels. Ask what is happening and who the
  actors are; agent names, the customer's intent, and which capability each screen is
  demonstrating are usually not inferable from the footage alone.
- Respect terminology instructions exactly (e.g. say "London Stock Exchange", not "MarketData").
- Keep lines short and concrete. Name what is on screen at that moment.
- Use the Azure realtime deployment details supplied by the user. Prefer Entra ID/keyless
  auth. Generate 24 kHz mono PCM with the requested voice, commonly Marin.
- When generating per chapter, tell the model **"this is one line from a longer
  continuous narration, do not add any greeting or sign-off"** or it will top and tail
  each line and the chapters won't join naturally.
- For excited Marin delivery: genuine enthusiasm, confident momentum, bright energy,
  crisp transitions, polished international business tone, lively but articulate pacing.
  Avoid robotic, flat, theatrical, or overacted delivery.
- Retry realtime generation on failure; websocket calls fail intermittently.
- Convert PCM to AAC/M4A and inspect duration before muxing.

## Audio mixing

- Normalize narration near -16 LUFS and keep true peak safely below 0 dBFS.
- Mix music quietly beneath narration with sidechain ducking so speech stays dominant.
- Fade music in and out cleanly.

FFmpeg gotchas that will silently ruin the mix:

- **`amix` defaults to `normalize=1`**, which divides every input by the input count and
  leaves the result far too quiet. Always set `normalize=0` and control balance with
  `weights`.
- **A narration bus shorter than the video ends the mix early**, leaving the outro
  silent. Use `apad=whole_dur=<total>` on the narration and `duration=longest` on the
  amix. Verify by scanning levels near the end, not by trusting the reported duration.
- **`atrim` leaves a timestamp offset.** Always follow it with `asetpts=PTS-STARTPTS`.
- Generate the music bed longer than you think you need; regenerating is cheap, and a bed
  that ends early is invisible until final QC.
- Finish with `loudnorm` → `alimiter` → `aresample=48000` → `atrim` to exact duration.

## Brand artifacts

**Canonical source:** https://brandcentral.microsoft.com/microsoft-brand/products/copilot.html

Every Copilot/Microsoft logo, icon, gradient, colour value, typeface, and motion asset used
in a demo video comes from that page. Brand Central is the authority on both the files and
the rules for using them; the product page carries the current Copilot logo lockups,
icon set, colour and gradient specifications, typography, and the do/don't usage guidance.

- **Never fabricate a brand mark.** Do not draw, AI-generate, trace, screenshot from a
  running app, or download from a web image search. If you cannot obtain the official
  file, say so and ship without the branding rather than substituting a lookalike.
- **Read colours and type from the downloaded assets, not from memory.** Sample the actual
  hex values out of the official SVG/PNG or the page's colour specification. Do not
  hardcode a Copilot gradient or accent colour you "remember" — it changes between brand
  refreshes and a wrong gradient is immediately obvious to a Microsoft audience.
- **Respect the usage rules published alongside the assets**: minimum clear space, minimum
  size, approved lockups, approved backgrounds. Do not recolour, rotate, distort,
  outline, add effects to, or crop a logo. Do not place a logo on a busy or low-contrast
  part of the frame.
- Prefer **SVG** for anything you rasterise yourself so title cards and lower thirds stay
  crisp at the delivery canvas size. Rasterise with an explicit density high enough for
  the canvas, then composite — never upscale a small PNG.
- Preserve transparency end to end. Compositing a logo that has been flattened onto white
  over a dark frame produces a visible white box.
- Match the mark to the product actually shown. A Microsoft 365 Copilot demo, a GitHub
  Copilot demo, and a Copilot Studio demo do not share the same lockup.

### Acquiring the assets

Brand Central is Entra/SAML-gated. Verified behaviour:

- Anonymous `curl` / web fetch of the Copilot page returns **HTTP 401**. There is no
  anonymous asset API (`/api/assets` returns 404).
- Auth is **SAML → session cookie**, not an OAuth-protected API, so there is no bearer
  token path. `az account get-access-token` does not help.
- The Copilot brand mark is **not** in `microsoft/fluentui-system-icons` (verified: zero
  matches across the whole repo). Do not go looking for it in public icon libraries, and
  do not substitute a generic "sparkle" icon for the Copilot logo.

Order of preference:

1. **Local cache** (below). If the asset is already there, use it — no auth of any kind.
   This is the normal path and the reason the cache exists. Populate it once, reuse forever.
2. **An already-authenticated browser session.** The user's everyday browser profile
   frequently already holds a valid `brandcentral.microsoft.com` cookie, in which case
   nothing new needs signing in — the page just opens. Check before asking for anything.
   Driving a *copy* of that profile headlessly is unreliable (Edge hangs, the network
   service crashes); if you go this route, open the page in the visible browser.
3. **Ask the user to download the pack** from the Brand Central Copilot page and drop it
   into the cache. This is usually faster than any automation.
4. **Ship unbranded** and say exactly which element was skipped.

Never attempt to sign in on the user's behalf, never ask for credentials, and never
substitute a lookalike mark when auth fails.

### Local brand asset cache

Persist everything fetched from Brand Central so later projects never re-download:

    ~/Documents/Microsoft Scout/assets/brand/
      copilot/
        logos/        official lockups, SVG preferred, PNG with alpha as fallback
        icons/        official Copilot icon set
        colors.json   hex values / gradient stops read from the official assets
        type/         approved typefaces if downloaded
      README.md       per-asset: source URL, download date, file format, dimensions,
                      background colour, and any usage constraint noted on Brand Central

Branded outro clips live separately in `~/Documents/Microsoft Scout/assets/outros/`.

Record the download date. Brand refreshes happen; if a cached asset is more than a few
months old and the video is customer-facing, re-check the Brand Central page before reuse.

## Branded outro

- Prefer an outro asset explicitly supplied or owned by the user.
- If none exists, build one from the official Brand Central assets (logo lockup on the
  approved background), not from a recreated mark.
- If the user points at a source video (possibly on an external drive), find it, sample
  frames near the end to locate the exact scene boundary, then binary-search a few
  timestamps to pin the transition to within ~0.2s.
- **Extract the outro with its original audio sting.** A silent outro feels broken. Check
  for an audio stream and keep it; let it play at its own level after the music fades.
- **Check the outro's background colour before padding.** Microsoft outros are typically
  on white, so padding with the default black produces obvious black bars. Pad with the
  matching colour.
- Re-encode to the project canvas and frame rate before concatenating, and verify the
  result with a rendered frame.
- **Save reusable outros to a shared asset library**, e.g.
  `~/Documents/Microsoft Scout/assets/outros/`, with a README recording the source,
  duration, dimensions, fps, whether it has audio, and its background colour. Do this
  proactively — these get reused across projects.

## Quality control

- Decode-check the final MP4 (`ffmpeg -v error -i final.mp4 -f null -`).
- Verify dimensions, frame rate, audio codec, duration, and file size with ffprobe.
- Measure loudness and true peak. Target roughly -16 LUFS integrated with peaks at or
  below about -1 dBFS.
- **Verify sync explicitly, don't assume it.** Sample a frame at the *midpoint of each
  spoken line* using the timeline offsets, tile them into one grid, and confirm each
  frame shows what its line describes. This catches drift that a plain contact sheet
  hides.
- Scan audio levels in windows across the whole timeline (start, middle, the last few
  seconds of body, and the outro) to catch dropouts and silent tails.
- **The `tile` filter with a `%02d` output pattern often writes only the final partial
  sheet.** Use `xstack` with an explicit layout to build review grids reliably, or size
  the tile grid to cover the entire clip in one image.
- Inspect any timestamps the user specifically flagged.
- **Render a frame of every branded element** (title card, lower third, watermark, outro)
  and check it against the Brand Central usage rules: correct lockup for the product,
  clear space respected, not distorted or recoloured, adequate contrast against the
  background, no white box from lost transparency.
- Keep the raw recording, per-chapter narration audio, narration source text, music
  generator, outro extract, and final master as separate files so later revisions never
  require re-recording.

## Delivery

- Lead with the completed outcome, duration, and a direct file path.
- Mention only meaningful changes such as corrected framing, sync, music, narration, and
  branded outro. Do not claim re-recording when none occurred.
- Surface trade-offs you made unilaterally (letterbox bars, slow-motion sections, cut
  content) and offer the alternative.
- State which brand assets were used and where they came from. If any branding was
  skipped because the official asset was unavailable, say so explicitly — never let the
  user assume a mark is official when it is not.
- State how cheap a revision is, so the user knows rewording a line is a minute's work.
