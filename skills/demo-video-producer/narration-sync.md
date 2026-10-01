# Narration-synchronised pipeline (working reference)

Proven on a 6.5-minute macOS screen recording of a mobile banking + Dynamics 365
contact centre demo (3024x1964 source, 390s raw, mixed windowed/full-screen, no audio),
delivered as a 3:05 narration-synced MP4.

Copy these four files into the project directory and edit only `chapters.py` to revise.

Revision loop:

    python3 gen_vo.py 05-dispute     # regenerate just the reworded line
    python3 build_synced.py
    python3 mix.py

---

## chapters.py

The only file you edit to revise. Each chapter is one narration line plus the source
cuts that show what the line describes.

```python
"""Chapter definitions: narration line + the raw-master source cuts it describes.

Each chapter's video is time-fitted to its own narration so the picture always
shows what the voice is describing.

cuts: list of (start, end, mode) in raw-master.mov seconds.
mode: P = phone-only crop, W = windowed browser, F = macOS full-screen
"""

CHAPTERS = [
    dict(
        id="01-open",
        text="Meet John. He's a retail banking customer, and he's just opened his US Bank mobile app.",
        cuts=[(0.6, 4.0, "P")],
    ),
    dict(
        id="02-maya",
        text="Instead of a menu tree, he's greeted by Maya, an AI banking agent who already knows exactly who he is. She greets him by name, in Arabic or English, his choice.",
        cuts=[(9.6, 13.4, "P"), (14.4, 18.4, "P")],
    ),
    dict(
        id="03-faq",
        text="John starts with a simple question. Which credit cards earn frequent flyer miles?",
        cuts=[(27.0, 31.5, "P")],
    ),
    dict(
        id="04-cards",
        text="Maya answers instantly from the bank's own product knowledge, recommending the Fabrikam Guest AltitudeX cards and walking through the travel perks that come with each one.",
        cuts=[(34.5, 40.0, "P"), (44.0, 48.0, "P")],
    ),
    dict(
        id="05-dispute",
        text="Then the conversation turns serious. John has spotted suspicious transactions, and he wants his card blocked.",
        cuts=[(55.4, 60.6, "P")],
    ),
    dict(
        id="06-whichcard",
        text="Because Maya has his full customer context, she doesn't ask him for a card number. She simply shows him the cards he actually holds and asks which one.",
        cuts=[(69.5, 76.2, "P"), (77.2, 80.2, "P")],
    ),
...(remaining chapters follow the same shape)...
```

---

## gen_vo.py

One Marin audio file per chapter, cached on disk. Pass chapter ids as arguments to
force-regenerate only those. Retries on transient websocket failures.

```python
#!/usr/bin/env python3
"""Generate one narration audio file per chapter via Azure OpenAI Realtime (Marin)."""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import sys
from pathlib import Path

import websockets

from chapters import CHAPTERS

ENDPOINT = "<your-foundry>.services.ai.azure.com"
DEPLOYMENT = "gpt-realtime-2.1"
API_VERSION = "2025-04-01-preview"
VOICE = "marin"
ROOT = Path(__file__).resolve().parent
OUTDIR = ROOT / "vo"

STYLE = (
    "You are narrating an exciting, premium enterprise banking technology demo. "
    "Use the Marin voice with genuine enthusiasm, confident momentum, bright energy, "
    "and a polished international business tone. Sound genuinely impressed by the "
    "innovation. Keep the pace lively but articulate and clearly enunciated. "
    "This is one line from a longer continuous narration, so do not add any greeting, "
    "sign-off, or extra words. Never sound robotic, flat, theatrical or overacted."
)


def access_token() -> str:
    return subprocess.check_output(
        ["az", "account", "get-access-token", "--resource",
         "https://cognitiveservices.azure.com", "--query", "accessToken", "-o", "tsv"],
        text=True,
    ).strip()


async def speak(token: str, text: str) -> bytes:
    uri = (f"wss://{ENDPOINT}/openai/realtime"
           f"?api-version={API_VERSION}&deployment={DEPLOYMENT}")
    audio = bytearray()
    async with websockets.connect(
        uri, additional_headers={"Authorization": f"Bearer {token}"},
        max_size=None, open_timeout=30, close_timeout=10,
    ) as ws:
        await ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": VOICE,
                "output_audio_format": "pcm16",
                "instructions": STYLE,
            },
        }))
        await ws.send(json.dumps({
            "type": "conversation.item.create",
            "item": {
                "type": "message", "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": ("Read the following line verbatim. Do not add, remove, "
                             "summarize, or introduce any words.\n\n" + text),
                }],
            },
        }))
        await ws.send(json.dumps({
            "type": "response.create",
            "response": {
                "modalities": ["audio", "text"],
                "instructions": "Read the supplied line exactly as written.",
            },
        }))
        while True:
            event = json.loads(await ws.recv())
            et = event.get("type", "")
            if et in {"response.audio.delta", "response.output_audio.delta"}:
                audio.extend(base64.b64decode(event["delta"]))
            elif et == "error":
                raise RuntimeError(json.dumps(event, indent=2))
            elif et in {"response.done", "response.completed"}:
                break
    if not audio:
        raise RuntimeError("no audio returned")
    return bytes(audio)


async def main() -> None:
    OUTDIR.mkdir(exist_ok=True)
    token = access_token()
    only = set(sys.argv[1:])
    for ch in CHAPTERS:
        if only and ch["id"] not in only:
            continue
        dest = OUTDIR / f"{ch['id']}.m4a"
        if dest.exists() and not only:
            print(f"  skip {ch['id']} (exists)")
            continue
        for attempt in range(3):
            try:
                pcm = await speak(token, ch["text"])
                break
            except Exception as exc:                      # noqa: BLE001
                print(f"  retry {ch['id']}: {exc}")
                await asyncio.sleep(3)
        else:
            raise SystemExit(f"failed: {ch['id']}")
        raw = OUTDIR / f"{ch['id']}.pcm"
        raw.write_bytes(pcm)
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", "24000", "-ac", "1",
             "-i", str(raw), "-c:a", "aac", "-b:a", "192k", str(dest)], check=True)
        raw.unlink()
        dur = float(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(dest)], text=True).strip())
        print(f"  {ch['id']}: {dur:6.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## build_synced.py

Renders each chapter at natural speed, time-fits it to its narration line with
clamped `setpts`, holds the last frame for any residual gap, and records exact
voiceover offsets to `timeline.json`.

```python
#!/usr/bin/env python3
"""Build a narration-synchronised cut.

For each chapter the video is time-fitted to its own narration line, so the
picture always shows what the voice is describing. Video that is shorter than
its narration is slowed (up to SLOW_MAX) and then holds on its last frame.
Video that is longer is gently sped up (down to FAST_MAX).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from chapters import CHAPTERS

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "raw-master.mov"
WORK = ROOT / "build"
VO = ROOT / "vo"

W, H = 1920, 1248
FPS = 30

VF = {
    "P": "crop=2530:1645:247:175,scale=1920:1248:flags=lanczos,setsar=1",
    "W": "crop=3024:1596:0:224,scale=1920:1013:flags=lanczos,"
         "pad=1920:1248:0:118:black,setsar=1",
    "F": "crop=3024:1930:0:34,scale=1920:1225:flags=lanczos,"
         "pad=1920:1248:0:12:black,setsar=1",
}

LEAD = 0.35      # silence before the narration line starts inside a chapter
TAIL = 0.55      # breathing room after the line ends
SLOW_MAX = 1.9   # never stretch motion more than this
FAST_MAX = 0.80  # never compress motion below this (i.e. max 1.25x speed)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def dur(path: Path) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], text=True).strip())


def main() -> None:
    WORK.mkdir(exist_ok=True)
    for f in WORK.glob("*"):
        f.unlink()

    timeline = []
    parts = []
    clock = 0.0

    for ci, ch in enumerate(CHAPTERS):
        cid = ch["id"]
        vo_file = VO / f"{cid}.m4a"
        vo_dur = dur(vo_file)
        target = LEAD + vo_dur + TAIL

        # --- render this chapter's raw video at natural speed ---
        seg_files = []
        for si, (s, e, mode) in enumerate(ch["cuts"]):
            f = WORK / f"{cid}-s{si}.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-ss", str(s), "-i", str(SRC),
                 "-t", str(round(e - s, 3)), "-vf", VF[mode], "-r", str(FPS),
                 "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-an", str(f)])
            seg_files.append(f)

        joined = WORK / f"{cid}-nat.mp4"
        if len(seg_files) == 1:
            seg_files[0].rename(joined)
        else:
            lst = WORK / f"{cid}-list.txt"
            lst.write_text("".join(f"file '{p.name}'\n" for p in seg_files))
            run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", str(lst), "-c", "copy", str(joined)])
        nat = dur(joined)

        # --- time-fit to the narration ---
        ratio = target / nat
        ratio = max(FAST_MAX, min(SLOW_MAX, ratio))
        fitted = WORK / f"{cid}-fit.mp4"
        run(["ffmpeg", "-y", "-v", "error", "-i", str(joined),
             "-vf", f"setpts={ratio:.5f}*PTS,fps={FPS}",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", "-an", str(fitted)])
        fit_dur = dur(fitted)

        # --- hold the last frame if the narration still overruns ---
        final = fitted
        gap = target - fit_dur
        if gap > 0.12:
            still = WORK / f"{cid}-last.png"
            run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.1", "-i", str(fitted),
                 "-frames:v", "1", str(still)])
            hold = WORK / f"{cid}-hold.mp4"
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(still),
                 "-t", f"{gap:.3f}", "-r", str(FPS), "-c:v", "libx264",
                 "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                 "-vf", "setsar=1", str(hold)])
            merged = WORK / f"{cid}-full.mp4"
            lst = WORK / f"{cid}-hlist.txt"
            lst.write_text(f"file '{fitted.name}'\nfile '{hold.name}'\n")
            run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                 "-i", str(lst), "-c", "copy", str(merged)])
            final = merged

        actual = dur(final)
        parts.append(final)
        timeline.append(dict(id=cid, start=round(clock, 3),
                             vo_at=round(clock + LEAD, 3),
                             vo_dur=round(vo_dur, 3),
                             nat=round(nat, 3), ratio=round(ratio, 3),
                             dur=round(actual, 3)))
        print(f"{cid:14s} nat {nat:6.2f}  vo {vo_dur:6.2f}  "
              f"x{ratio:4.2f}  -> {actual:6.2f}  @ {clock:7.2f}")
        clock += actual

    lst = WORK / "all.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c", "copy", str(ROOT / "body-silent.mp4")])
    (ROOT / "timeline.json").write_text(json.dumps(timeline, indent=2))
    print(f"\nbody-silent.mp4 = {dur(ROOT / 'body-silent.mp4'):.2f}s")


if __name__ == "__main__":
    main()
```

---

## mix.py

Delays each chapter voiceover to its offset, ducks the music bed under the narration
bus, masters the body, then concatenates the outro so the outro keeps its own sting.

```python
#!/usr/bin/env python3
"""Assemble the narration track at exact chapter offsets, mix with music,
append the Microsoft outro (keeping its own audio sting), and master."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VO = ROOT / "vo"
FINAL = ROOT / "US-Bank-Maya-to-Marco-CCaaS-Demo.mp4"


def dur(p) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(p)], text=True).strip())


def main() -> None:
    tl = json.loads((ROOT / "timeline.json").read_text())
    body = ROOT / "body-silent.mp4"
    body_dur = dur(body)
    outro = ROOT / "outro-project.mp4"
    outro_dur = dur(outro)
    total = body_dur + outro_dur
    print(f"body {body_dur:.2f}s + outro {outro_dur:.2f}s = {total:.2f}s")

    # ---- narration bus: each line delayed to its chapter offset ----
    inputs, chains, labels = [], [], []
    for i, ch in enumerate(tl):
        inputs += ["-i", str(VO / f"{ch['id']}.m4a")]
        ms = int(round(ch["vo_at"] * 1000))
        chains.append(f"[{i}:a]aresample=48000,adelay={ms}|{ms},"
                      f"apad=whole_dur={total:.3f}[v{i}]")
        labels.append(f"[v{i}]")
    n = len(tl)
    chains.append(f"{''.join(labels)}amix=inputs={n}:duration=longest:"
                  f"dropout_transition=0:normalize=0,"
                  f"loudnorm=I=-16:TP=-1.5:LRA=11,"
                  f"apad=whole_dur={total:.3f},asplit=2[nar][key]")

    # ---- music bed ----
    inputs += ["-i", str(ROOT / "music-bed.wav")]
    mi = n
    fade_out_at = max(0.0, body_dur - 2.5)
    chains.append(f"[{mi}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                  f"volume=0.30,afade=t=in:st=0:d=2,"
                  f"afade=t=out:st={fade_out_at:.2f}:d=2.5[mus]")
    chains.append("[mus][key]sidechaincompress=threshold=0.028:ratio=9:"
                  "attack=8:release=420:makeup=1[duck]")
    chains.append("[nar][duck]amix=inputs=2:duration=longest:"
                  "dropout_transition=0:normalize=0:weights='1 0.85',"
                  "loudnorm=I=-16:TP=-1.0:LRA=11,alimiter=limit=0.93,"
                  f"aresample=48000,atrim=0:{body_dur:.3f}[bodyaud]")

    body_audio = ROOT / "body-audio.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs,
                    "-filter_complex", ";".join(chains),
                    "-map", "[bodyaud]", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2", str(body_audio)], check=True)
    print(f"body audio {dur(body_audio):.2f}s")

    # ---- mux body, then concat with the outro (outro keeps its own sting) ----
    body_av = ROOT / "body-av.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(body),
                    "-i", str(body_audio), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "copy", "-shortest",
                    str(body_av)], check=True)

    lst = ROOT / "final.txt"
    lst.write_text(f"file '{body_av.name}'\nfile '{outro.name}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                    str(FINAL)], check=True)
    print(f"FINAL {dur(FINAL):.2f}s -> {FINAL.name}")


if __name__ == "__main__":
    main()
```

---

## Supporting snippets

### Resolve a macOS screen recording filename (U+202F trap)

```bash
# The space before "AM" is U+202F, not ASCII space — literal paths fail.
SRC=$(ls ~/Downloads/Screen\ Recording\ 2026-08-12*11.11.54*.mov | head -1)
cp "$SRC" raw-master.mov
```

### Detect windowed vs full-screen ranges

```python
import subprocess, numpy as np
# Sample a 10x10 patch bottom-left; light = full-screen app panel, dark = wallpaper/Dock.
# Probe the BOTTOM, never the top: full-screen frames have a dark top strip.
X, Y, FPS = 60, 1948, 2
raw = subprocess.run(
    ["ffmpeg","-v","error","-i","raw-master.mov",
     "-vf",f"fps={FPS},crop=10:10:{X}:{Y}","-f","rawvideo","-pix_fmt","rgb24","-"],
    capture_output=True).stdout
a = np.frombuffer(raw, np.uint8).reshape(-1,10,10,3).mean(axis=(1,2))
for i,(r,g,b) in enumerate(a):
    print(i/FPS, "F" if min(r,g,b) > 150 else "W")
```

### Crop modes onto one canvas (3024x1964 -> 1920x1248)

```python
VF = {
    "P": "crop=2530:1645:247:175,scale=1920:1248:flags=lanczos,setsar=1",
    "W": "crop=3024:1596:0:224,scale=1920:1013:flags=lanczos,"
         "pad=1920:1248:0:118:black,setsar=1",
    "F": "crop=3024:1930:0:34,scale=1920:1225:flags=lanczos,"
         "pad=1920:1248:0:12:black,setsar=1",
}
# W and F share the same horizontal scale (0.635) so the UI is the same physical
# size across cuts. Vertical padding absorbs the difference.
```

### Extract a branded outro with its audio sting

```bash
# 1. sample frames near the end to find the scene boundary
for t in 62 65 68 70 72 74 76; do
  ffmpeg -v error -y -ss $t -i source.mp4 -frames:v 1 -vf "scale=480:-1" o$t.png; done
# 2. binary-search a few timestamps to pin the transition, then extract
ffmpeg -y -ss 72.4 -i source.mp4 -c:v libx264 -crf 17 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart microsoft-standard-outro.mp4
# 3. re-encode to the project canvas — PAD WITH WHITE for Microsoft outros
ffmpeg -y -i microsoft-standard-outro.mp4 \
  -vf "scale=1920:1080:flags=lanczos,pad=1920:1248:0:84:white,setsar=1,fps=30" \
  -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac -b:a 192k outro-project.mp4
```

### Sync verification grid

```python
import json, subprocess, pathlib
tl = json.loads(pathlib.Path("timeline.json").read_text())
for ch in tl:
    t = ch["vo_at"] + ch["vo_dur"] / 2      # midpoint of the spoken line
    subprocess.run(["ffmpeg","-v","error","-y","-ss",f"{t:.2f}","-i","final.mp4",
        "-frames:v","1","-vf",
        f"scale=480:-1,drawtext=text='{ch['id']}':x=8:y=8:fontsize=22:"
        "fontcolor=yellow:box=1:boxcolor=black@0.7", f"qc/s-{ch['id']}.png"], check=True)
# Then tile with xstack (NOT the tile filter with %02d, which drops sheets).
```

### Audio level scan across the timeline

```python
import subprocess
for a, b in [(0,5),(60,65),(120,125),(170,175),(180,183),(183,185)]:
    err = subprocess.run(["ffmpeg","-hide_banner","-ss",str(a),"-t",str(b-a),
        "-i","final.mp4","-vn","-af","volumedetect","-f","null","-"],
        capture_output=True, text=True).stderr
    print(a, b, [l.split(":")[-1].strip() for l in err.splitlines()
                 if "mean_volume" in l or "max_volume" in l])
```


## Overlay rails and animated cards (learned the hard way)

### `fade=in:alpha=1` silently does nothing on a single-frame PNG input
An `-i card.png` input is **one frame at PTS 0**. `overlay` holds that frame for the whole
clip, but `fade` only ever sees PTS 0, so alpha stays at the start of the ramp — i.e. **zero**,
forever. The card is invisible in the exact chapter it was supposed to animate into, and
appears (correctly) only in later chapters where no fade is applied.

Always loop the input you intend to fade:

```
# fading card
-loop 1 -framerate 30 -t <chapter_duration> -i card5.png
# static (already-revealed) cards need no loop
-i card1.png
```

### Composite the rail AFTER the setpts time-fit
If you overlay before time-fitting, `setpts` stretches the fade too and the animation speed
varies per chapter. Render backdrop+content -> time-fit -> then a second pass that overlays
the rail with fade times relative to the *final* chapter length.

### Killing black bars without cropping away UI
Side-cropping a 3024x1964 recording to 16:9 clips real UI (side panels, Copilot rails).
Instead composite onto the target canvas over a blurred copy of the same frame:

```
[0:v]split=2[bg][fg];
[bg]crop=<mode>,scale=1920:1080,boxblur=30:2,eq=brightness=-0.10:saturation=0.6[b];
[fg]crop=<mode>,scale=1860:-2:flags=lanczos[f];
[b][f]overlay=(W-w)/2:(H-h)/2[out]
```

Scale **every** mode's foreground to the *same* width (1860) so the UI does not visibly
resize when the recording toggles between windowed and full-screen.

For phone-only chapters, crop just the phone body, place it on one side, and use the
remaining space for the card rail — no need to shrink the phone.

## Screen-recording artifacts hide in the *desktop*, not just the app

macOS notification / Teams meeting-reminder popups look like stray window chrome
(they carry their own red-yellow-green traffic lights) and reviewers report them as
"I can still see minimize/maximize". They can be sub-2-second and invisible in a
1-fps contact sheet.

Detect them by diffing a small greyscale patch of the popup region against a known
"popup present" reference, stepping 0.25 s:

```python
BOX = "700:120:2180:1380"     # raw coords of the popup title strip
def g(t):
    out = subprocess.check_output(["ffmpeg","-v","error","-ss",f"{t}","-i",SRC,
        "-frames:v","1","-vf",f"crop={BOX},scale=70:12",
        "-f","rawvideo","-pix_fmt","gray","-"])
    return np.frombuffer(out, dtype=np.uint8).astype(float).reshape(12,70)
```

A near-zero mean absolute difference means the popup is on screen. Use a **tight**
box: a large box also matches unrelated layout changes and produces false ranges.
Then move every overlapping cut clear of the range with ~1 s of margin.

## Don't crop the bottom to dodge the Dock without checking what else is down there

Agent-desk UIs put the compose box, quick replies and channel actions at the very
bottom of a panel. In this recording the action bar sat at raw y≈1900 while the
Dock top was y≈1837 — so a single "safe" bottom crop either ate the Dock **or** the
controls being demoed, depending on window mode. Measure both per mode:

- full-screen: no Dock, so crop right down to the action bar
- windowed: crop must stop above the Dock, but the window's own bottom is higher anyway

Then pick **one common foreground width** for both modes so the UI never changes
size. The width is bounded by the *tallest* crop still fitting 1080 px:
`common_w = 1080 * src_w / tallest_crop_h`. Anything wider makes the tall mode
overflow and forces per-mode scaling — which is exactly the "constant resizing"
artifact reviewers notice.

## Keep the subject where the user framed it

When adding an overlay rail, resist moving the subject. If the source already has
dead space (here, wallpaper to the left of an iPhone simulator), crop a 16:9 window
that leaves the subject in its original position and size the overlay to fit the
space that already exists. Moving the subject reads as a heavier edit than it is and
is the first thing a reviewer objects to.

## Iconography follows the story, not the plumbing

A reviewer may want every step badged with the *orchestrator's* logo (Copilot Studio)
even when the underlying service differs (Azure SQL, Azure OpenAI), keeping the
service name in the card subtitle. Keep icon choice and copy as separate fields in
the card definition so this is a one-line change.

## A long freeze-hold before the outro reads as "the outro is missing"

If a closing chapter has far less source than narration, the freeze-hold can run for
several seconds and viewers perceive the frozen app screen as the start of the outro.
Give the final chapter enough source that the hold stays under ~2 s, splitting the cut
around any artifact rather than accepting a single short range.

## "The outro is missing" is almost always a concat/timestamp fault

If the body is assembled with the **concat demuxer + `-c copy`** (which it is, in this
pipeline - 20 identically encoded chapters), then the outro must be encoded with the
**exact same parameters** and appended the same way. Three things all fail:

1. **copy-concat of a differently encoded outro** - two independent H.264 segments in
   one container. ffprobe reports the full duration and ffmpeg decodes it fine, so it
   looks correct in every automated check, but QuickTime/Preview/Quick Look stop at
   the first segment's end. The reviewer sees no outro.
2. **Re-encoding across the join with the `concat` filter** - inherits the timestamp
   discontinuities from the copy-concatenated body. Observed: a 4.57 s outro stretched
   to 7.97 s of timeline (123 frames spread over 8 s of PTS).
3. **Adding `setpts=PTS-STARTPTS` after `fps=30` to fix (2)** - overcorrects and drops
   frames; output came out *shorter* than the body alone.

The fix that works: keep one homogeneous video chain.

```bash
# outro video, encoded EXACTLY like every chapter
ffmpeg -i outro.mp4 -an -vf "scale=1920:1080,setsar=1,fps=30,format=yuv420p" \
  -r 30 -fps_mode cfr -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p outro-silent.mp4
# outro sting extracted separately
ffmpeg -i outro.mp4 -vn -c:a aac -b:a 192k -ar 48000 -ac 2 outro-sting.m4a
```

Append `outro-silent.mp4` to the chapter list in the same copy-concat, and mix the
sting into the master audio bus with `adelay=<body_dur_ms>`. One video stream, one
audio stream, one mux.

**Verify with frame count, not duration**: `expected == round(total_seconds * fps)`.
Duration alone hides both the stretch and the drop.

```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=nb_read_frames,duration,avg_frame_rate -of csv=p=0 out.mp4
```

## Trim a lifted outro on a luma threshold, not a guess

Binary-searching the "content -> white card" boundary to 0.1 s still left two frames of
the source app UI at the head of the clip - invisible in a contact sheet, obvious when
a reviewer steps the first frames. Sample mean luma at 0.02 s steps across the
boundary and cut on the step change (here 228.0 -> 253.2 at t=72.44), then confirm by
exporting frames 0-3 with `-vsync 0`.
