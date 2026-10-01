# AI Agent Skills

Reusable, battle-tested **agent skills** for building Microsoft 365 Copilot agents, Dynamics 365
demos and Power Platform solutions.

**[→ Browse the gallery](https://erturkm.github.io/ai-agent-skills/)**

A skill is a structured instruction set that an AI coding agent reads and follows to do real
engineering work. Not documentation — procedure. Each one encodes the traps, the verification
steps and the "this looks like it worked but didn't" failure modes that only show up once you
have actually shipped the thing.

## Skills

| Skill | What it does |
|---|---|
| **[copilot-mcp-app](skills/copilot-mcp-app/SKILL.md)** | Build a Microsoft 365 Copilot declarative agent backed by a remote MCP server that reads and writes live Dataverse data and renders interactive D365-styled React widgets inside Copilot chat. |
| **[build-d365](skills/build-d365/SKILL.md)** | End-to-end Dynamics 365 / Power Platform demo engineering via the Dataverse Web API — schema, form XML surgery, model-driven apps, BPFs, Power Automate, Copilot Studio agents, PCF controls. |
| **[cij-marketing](skills/cij-marketing/SKILL.md)** | Build Dynamics 365 Customer Insights – Journeys real-time marketing assets: segments, branded emails, content blocks, SMS, push and multi-touchpoint journeys. |
| **[demo-video-producer](skills/demo-video-producer/SKILL.md)** | Turn a screen recording into a polished demo video — narration-synchronised cuts, AI voiceover, original music beds, branded outros. |

## Installing

Clone the repo and copy any skill folder into your agent's skills directory:

```bash
git clone https://github.com/erturkm/ai-agent-skills.git
cp -R ai-agent-skills/skills/copilot-mcp-app ~/.copilot/m-skills/
```

Then invoke it with `/copilot-mcp-app`, or just describe your task — skills match on their
description automatically.

Works with **GitHub Copilot CLI** and **Microsoft Scout**. The format is plain Markdown with
YAML frontmatter, so it ports to most agent runtimes with little effort.

## Anatomy of a skill

```
skills/copilot-mcp-app/
├── SKILL.md              # frontmatter (name, description) + the main playbook
└── reference/            # deep-dive files the agent reads on demand
    ├── mcp-server.md
    ├── widget.md
    └── …
```

`SKILL.md` carries the decision-making: build order, architecture, the rules that save days.
Reference files carry the detail. Splitting them keeps the main file readable while letting the
agent pull depth only when a task needs it.

The `description` in the frontmatter is what the agent matches against, so it is written to be
greedy about trigger terms rather than elegant.

## A note on provenance

These were extracted from working implementations, not written speculatively. Customer names,
tenant identifiers and internal project codenames have been replaced with neutral placeholders
(`Contoso`, `<your-org>.crm.dynamics.com`). Where a skill cites a lesson as hard-won, it was.

## Caveat

Skills are instruction sets, not executable code — but they instruct an agent to *run* things.
Read a skill before pointing it at a production tenant. Several of these create, modify and
delete Dataverse records.

## Licence

MIT — see [LICENSE](LICENSE).
