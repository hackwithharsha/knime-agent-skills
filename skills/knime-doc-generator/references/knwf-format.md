# KNIME `.knwf` format notes

KNIME publishes no formal schema for this format. Everything here was
reverse-engineered from real exports (KNIME 4.4.2) and cross-checked against scattered
official docs and forum mentions. **Real samples are the source of truth** — several
details below, notably the metanode/component split and the `%%NNNNN` text escape, are
documented nowhere and were confirmed only by inspecting actual files.

`scripts/knime_doc/` already implements all of this. Read this file when the parser hits
something unexpected, or when writing a new skill that needs the same structure.

## Container

- **`.knwf` is a zip file.** The top-level entry is `<Workflow Name>/workflow.knime`.
- Entries are read with `ZipFile.read()` into memory and never extracted to disk, which
  sidesteps zip-slip entirely. XML that declares a DTD or entities is refused before a
  parser sees it — a real KNIME config never has one, and that declaration is what
  entity-expansion and XXE attacks need. `defusedxml` is used additionally when it
  happens to be installed, but is not required.

## `workflow.knime`

XML in KNIME's generic `NodeSettings` config format
(`xmlns="http://www.knime.org/2008/09/XMLConfig"`) — a key-value tree of:

- `<entry key=".." type=".." value="..">` — scalar. Types: `xstring`, `xint`, `xboolean`,
  `xdouble`. `isnull="true"` means unset.
- `<config key="..">...</config>` — nested.

Keys that matter:

| Path | Meaning |
| --- | --- |
| `entry name` | Workflow display name. Often `isnull="true"`, in which case fall back to the folder name. |
| `config annotations` → `annotation_N` → `entry text` | Free-form canvas annotations — the best workflow-level description candidate. |
| `config nodes` → `node_<id>` | `entry id`, `entry node_settings_file` (relative path), `entry node_is_meta`, `entry node_type` (`NativeNode` \| `SubNode` \| `MetaNode`). |
| `config connections` → `connection_N` | `entry sourceID`, `destID`, `sourcePort`, `destPort`. |

Arrays are encoded as a config with an `array-size` entry plus numerically-keyed
entries/configs (`"0"`, `"1"`, …).

## Text escaping quirk

Annotation and description text embeds control characters as fixed-width `%%NNNNN`
tokens: two percent signs plus a 5-digit zero-padded decimal codepoint, **with no closing
`%%`**. Tokens concatenate directly — `%%00013%%00010` is two back-to-back tokens (CR+LF),
not one wrapped token.

A regex expecting a trailing `%%` misparses this: it consumes the next token's leading
`%%` as its own closing delimiter and corrupts every token after the first. This must be
decoded manually; it is not standard XML entity escaping, which ElementTree already
handles.

## Per-node `settings.xml`

For `NativeNode` and `SubNode`, its own root config contains:

- `model` — the actual node configuration. SQL, file paths, expressions, and filters all
  live here.
- `nodeAnnotation` — per-node canvas annotation.
- `customDescription` — the user's own description of the node.
- `state`
- near the bottom: `factory` (fully-qualified Java class — the node's type identity),
  `node-name` (human label, e.g. "SQLite Connector"), `name` (instance display name;
  differs from `node-name` only if the user renamed it), `ports`, `filestores`.

### `model` settings are noisy

Two categories carry zero documentation value and are skipped by the parser:

- **Type-mapping blocks.** Nodes with DB/type-mapping (e.g. DB Connectors) embed
  `external_to_knime_mapping` / `knime_to_external_mapping` enumerating ~30 JDBC-type
  conversion rules — hundreds of lines of pure boilerplate.
- **`_Internals` keys** (e.g. `dbTable_Internals`) — KNIME's `SettingsModelID` /
  `EnabledStatus` wrapper metadata.

UI/layout keys (coordinates, colors, font sizes, `layoutJSON`) are skipped too.

## Flow variables

A setting parameterized by a flow variable shows up as a `used_variable` or
`exposed_variable` string entry nested inside the relevant config, e.g.
`sqlite-connection/path/used_variable = "SqlitePath"`.

Flow-variable **overrides** (the Flow Variables tab) live in a separate top-level
`variables/tree` block that mirrors `model`'s shape — not inside `model` itself. Both have
to be checked.

## Metanodes vs. components — structurally different

**MetaNode** (legacy):

- `node_settings_file` in the parent points **directly** at a nested
  `<subfolder>/workflow.knime`. There is no wrapping `settings.xml`.
- Its name lives in that nested `workflow.knime`'s `entry name`.
- Ports are declared via `meta_in_ports` / `meta_out_ports` configs.

**SubNode** (component — the current UI concept):

- `node_settings_file` points at `<subfolder>/settings.xml`, which has **no `factory` and
  no `name`/`node-name` entry**. Instead it has `entry workflow-file` (= `"workflow.knime"`,
  a sibling in the same folder) and `virtual-in-ID` / `virtual-out-ID` (the ids of the
  internal `Component Input` / `Component Output` boundary nodes).
- The component's true display name comes from that nested `workflow.knime`'s `entry name`.
  The containing folder name can be a truncated or sanitized variant and should not be
  trusted as the display name.

Both recurse identically otherwise: the nested `workflow.knime` has its own
`nodes`/`connections`, scoped independently. **Child node ids are not guaranteed unique
against the parent's id space.**

## Secrets

Credential fields appear as `config password` → `entry credentials` — a KNIME Credential
reference rather than a raw password in the samples seen, but the field name is the
reliable signal.

The parser redacts on key-name match (`password`, `credential`, `secret`, `token`,
`apikey`, `api_key`, `auth`) regardless of value, plus any string value matching an
embedded-userinfo URL (`scheme://user:pass@host`). A matching **key** redacts the whole
subtree before recursing — a credential block can be a nested config, not just a string,
and an earlier version that only checked scalar values let those through untouched.

`.knwf` is untrusted user input. Treat redaction as a filter, not a guarantee: a literal
token inside a SQL string or a Java snippet will not match either rule.
