# KNIME Agent Skills

Ask Claude what a KNIME workflow does, and get a proper document back.

Attach a `.knwf` export to a Claude conversation and this skill reads the workflow, works sout what it reads, what it writes and what happens in between, and hands you a formatted PDF.

> [!WARNING]
> **Early development.** The skill is in alpha. It works on most workflows, but some nodes are still unrecognized and some edge cases aren't handled yet. If you find a workflow that doesn't work, please open PR.

## Install it in Claude (5 minutes, once)

**1. Download the skill file**

[⬇ **Download knime-doc-generator.zip**](../../raw/main/dist/knime-doc-generator.zip)

Save it somewhere you can find it. Don't unzip it, Claude wants the zip as is.

**2. Add it to Claude**

1. Go to [claude.ai](https://claude.ai) and sign in.
2. Open **Settings → Capabilities → Skills**.
3. Click **Upload skill** and pick the zip you just downloaded.

That's it. The skill stays in your account and is available in every new conversation.

## Use it

Start a conversation, attach your `.knwf` file, and ask in your own words:

> Document this knime workflow.

or

> What does this workflow actually do? Where does the data come from?

### Getting the `.knwf` out of KNIME

In KNIME Analytics Platform: right-click the workflow in the explorer → **Export KNIME
Workflow…** → save the `.knwf` file. (Not "Save As" - that isn't an export.)

## What you get

A PDF with five sections, in this order, and nothing invented:

| Section | What's in it |
| --- | --- |
| **Purpose** | What problem the workflow solves, in a paragraph |
| **Inputs** | Every data source, node name, format, and where it reads from |
| **Outputs** | Every destination the workflow writes to |
| **Transformation Steps** | What happens in between, grouped into logical stages |
| **Notes** | Hardcoded paths, retry logic, credential handling, caveats |

Every document is marked as `AI-generated`. Read it before you circulate it.

## Your data

- **The workflow file goes to Claude.** It's read inside Claude's sandbox in your own
  conversation, not sent anywhere else and not used to train models on paid plans. But, it does leave your machine. if your organization has rules about that, check them first.
- **Passwords and credentials are stripped before Claude reads them.** Fields named like secrets (`password`, `credential`, `token`, `apikey`, …) and connection strings with embedded logins are replaced with `[REDACTED]` by the parser.
- **That's a filter, not a guarantee.** A secret typed into the middle of a SQL query or
  a Java snippet won't match those rules. If a workflow contains something sensitive in an unusual place, treat the conversation accordingly.
- Nothing here calls out to the internet, and no API key is needed.

## Available skills

| Skill | What it does | Version |
| ----- | ------------ | ------- |
| [knime-doc-generator](skills/knime-doc-generator/SKILL.md) | Documents a `.knwf` workflow as a five-section PDF | 0.2.0 |