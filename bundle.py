#!/usr/bin/env python3
"""
Bundle each skill (SKILL.md + reference/*.md) into a single self-contained .md,
and build one combined file containing every skill.

Internal "reference/foo.md" links are rewritten to in-document anchors so the
bundle works standalone. Frontmatter is preserved on per-skill bundles so the
file still registers as a skill when dropped in as <skill>/SKILL.md.
"""
import re
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKILLS = ROOT / "skills"
DIST = ROOT / "dist"

ORDER = ["copilot-mcp-app", "build-d365", "cij-marketing", "demo-video-producer"]

FM = re.compile(r"\A---\n(.*?)\n---\n", re.S)
REFLINK = re.compile(r"(?<!\w)(?:\./)?(?:reference/)?([a-z0-9-]+\.md)(?!\w)", re.I)


def anchor(stem: str) -> str:
    return "appendix-" + re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def split_fm(text: str):
    m = FM.match(text)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def demote(text: str, levels: int = 1) -> str:
    """Push headings down so appendix content nests under its ## heading."""
    out = []
    fence = False
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
        if not fence and re.match(r"^#{1,5} ", line):
            line = "#" * levels + line
        out.append(line)
    return "\n".join(out)


def rewrite_links(text: str, known: dict) -> str:
    """Point reference/foo.md at the in-document appendix anchor."""
    fence = False
    out = []
    for line in text.split("\n"):
        s = line.lstrip()
        if s.startswith("```") or s.startswith("~~~"):
            fence = not fence
            out.append(line)
            continue
        if not fence:
            def sub(m):
                fn = m.group(1).lower()
                if fn in known:
                    return f"#{known[fn]}"
                return m.group(0)
            line = REFLINK.sub(sub, line)
        out.append(line)
    return "\n".join(out)


def collect(skill: str):
    d = SKILLS / skill
    main = d / "SKILL.md"
    refs = sorted((d / "reference").glob("*.md")) if (d / "reference").is_dir() else []
    # loose siblings (e.g. demo-video-producer/narration-sync.md)
    refs += sorted(p for p in d.glob("*.md") if p.name != "SKILL.md")
    return main, refs


def build_skill(skill: str, standalone: bool = True) -> str:
    main, refs = collect(skill)
    known = {p.name.lower(): anchor(p.stem) for p in refs}

    fm, body = split_fm(main.read_text(encoding="utf-8"))
    body = rewrite_links(body, known).strip()

    parts = []
    if standalone and fm:
        parts.append(f"---\n{fm}\n---\n")

    if refs:
        toc = "\n".join(
            f"- [{p.stem.replace('-', ' ').title()}](#{anchor(p.stem)})" for p in refs
        )
        parts.append(
            f"> **Bundled skill file.** This single document contains `SKILL.md` plus all "
            f"{len(refs)} reference file(s), inlined as appendices below. Cross-references "
            f"have been rewritten to in-page links.\n>\n"
            f"> **Appendices:**\n> " + toc.replace("\n", "\n> ") + "\n"
        )

    parts.append(body)

    for p in refs:
        rfm, rbody = split_fm(p.read_text(encoding="utf-8"))
        rbody = rewrite_links(rbody, known).strip()
        title = p.stem.replace("-", " ").title()
        parts.append(
            f"\n---\n\n<a id=\"{anchor(p.stem)}\"></a>\n\n"
            f"## Appendix: {title}\n\n"
            f"*Originally `{'reference/' if (SKILLS/skill/'reference'/p.name).exists() else ''}{p.name}`*\n\n"
            + demote(rbody, 1)
        )

    return "\n\n".join(parts).rstrip() + "\n"


def main():
    DIST.mkdir(exist_ok=True)
    meta = []

    for skill in ORDER:
        text = build_skill(skill, standalone=True)
        out = DIST / f"{skill}.md"
        out.write_text(text, encoding="utf-8")
        main_f, refs = collect(skill)
        meta.append({
            "id": skill,
            "files": 1 + len(refs),
            "bytes": len(text.encode()),
        })
        print(f"  {skill:24} {1+len(refs)} files -> {len(text.encode())/1024:6.1f} KB")

    # combined
    combined = [
        "# AI Agent Skills — Complete Bundle\n",
        "Every skill in one file. Each section below is a complete, self-contained skill "
        "including its reference material.\n",
        "Source: https://github.com/erturkm/ai-agent-skills\n",
        "## Contents\n",
    ]
    for skill in ORDER:
        combined.append(f"- [{skill}](#skill-{skill})")
    combined.append("")

    for skill in ORDER:
        fm, _ = split_fm((SKILLS / skill / "SKILL.md").read_text(encoding="utf-8"))
        desc = ""
        if fm:
            m = re.search(r'description:\s*"(.*?)"\s*$', fm, re.S | re.M)
            if m:
                desc = m.group(1)
        body = build_skill(skill, standalone=False)
        combined.append(
            f"\n---\n\n<a id=\"skill-{skill}\"></a>\n\n# Skill: `{skill}`\n\n"
            + (f"> {desc}\n\n" if desc else "")
            + demote(body, 1)
        )

    ctext = "\n".join(combined).rstrip() + "\n"
    (DIST / "all-skills.md").write_text(ctext, encoding="utf-8")
    print(f"  {'all-skills':24} combined  -> {len(ctext.encode())/1024:6.1f} KB")

    (DIST / "bundles.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
