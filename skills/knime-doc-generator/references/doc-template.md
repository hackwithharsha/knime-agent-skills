# Document template

Every generated document contains exactly these five sections, in this order, with these
exact headings:

```markdown
## Purpose
## Inputs
## Outputs
## Transformation Steps
## Notes
```

`scripts/export_pdf.py` checks for them and warns when one is missing or out of order. Nothing
goes above `## Purpose` — the exporter renders the title, generated date, and AI
disclaimer itself.

## Section rules

### Purpose

One short paragraph: what problem the workflow solves.

Draw it from the workflow's `description` (canvas annotations) or a node annotation that
states intent. If nothing supports a business purpose, write exactly:

> To be confirmed by workflow owner.

Do not infer purpose from node names. "Reads a CSV and writes to a database" is a
description of the mechanics, not a purpose, and a reader can already see it in the other
sections.

### Inputs

One bullet per source node. Each names three things:

1. The node name, verbatim and bolded.
2. Its data type or format, inferred from `factory` and `settings`.
3. Its location or identifier — file path, table name, connection target — exactly as it
   appears in the settings.

Source nodes are those with `is_source: true`, plus any node with no incoming connections
that reads external data. `is_source` is a keyword heuristic over the node name and
factory class, so check it against the connection graph rather than trusting it blindly.

### Outputs

The same three fields, for sink nodes: `is_sink: true`, plus any node with no outgoing
connections that writes or exports data.

### Transformation Steps

Numbered steps, one per **logical stage** — not one per node. A stage is what an engineer
would name when explaining the workflow to a colleague: "read and validate input",
"retry loop", "join against the lookup table", "format and write".

Each step names the nodes it contains, verbatim, and says in one grounded sentence what
the stage does. Ten nodes might be four steps.

### Notes

Caveats, limitations, and configuration details worth flagging, drawn only from what the
workflow shows:

- Hardcoded paths or connection targets
- Retry, loop, or error-handling behavior
- Credential handling, including fields that came back `[REDACTED]`
- Behavior that only applies in a particular environment (e.g. KNIME Server)
- Anything a reader would need before safely re-running the workflow

If `meta.settings_trimmed` was `true`, `meta.trim_note` goes here as the first bullet,
verbatim.

If there is genuinely nothing notable, write `None.`

## Style

- Bullets and numbered lists, not prose walls.
- Short sentences.
- No marketing language: not "powerful", "robust", "seamlessly", "cutting-edge",
  "state-of-the-art".
- Node names, file paths, variable names, and table names in `backticks` or **bold** —
  consistently, so a reader can tell verbatim workflow identifiers from your prose.
- Never state a fact the workflow data does not support.

## Worked example

````markdown
## Purpose

Establishes a SQLite database connection with retry logic, attempting the connection up
to a configured number of times before failing the workflow.

## Inputs

- **Table Creator** — in-memory dummy table, created inline (annotation: "Dummy Table")
- **SQLite Connector** — SQLite database; path supplied by the `SqlitePath` flow variable

## Outputs

- **DB Reader** — reads the table selected by **DB Table Selector** into a KNIME table
- **Fail Workflow** (component) — raises a workflow error when no connection succeeded

## Transformation Steps

1. **Counting Loop Start** begins the retry loop, bounded by its configured iteration
   count (annotation: "5 iterations").
2. **Try (Variable Ports)** / **Catch Errors (Var Ports)** wrap the connection attempt so
   a failure does not abort the workflow.
3. **SQLite Connector** attempts the connection using `SqlitePath`.
4. **Variable Condition Loop End** exits the loop on success or when the retry count is
   exhausted.
5. **Fail Workflow** inspects the outcome via **Extract Table Dimension** and
   **Breakpoint**, failing the run if every attempt failed.

## Notes

- The SQLite path is parameterized through the `SqlitePath` flow variable, not hardcoded.
- **Fail Workflow** matters only on KNIME Server, where it marks the overall execution
  unsuccessful.
- Retry count is configured on **Counting Loop Start**; set it to `<= 3` to simulate
  exhausted retries.
````

Note what this example does *not* do: it does not claim the workflow exists to "ensure
reliable data access for downstream analytics". Nothing in the workflow says that.
