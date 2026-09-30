"""Deterministic helpers for the knime-doc-generator skill.

Split so that the two CLI entrypoints stay thin:
  - xmlconfig / models / knwf / budget  -> .knwf  ->  workflow JSON
  - markdown_render / pdf_exporter / style / filenames  -> markdown  ->  PDF

Nothing here calls an LLM. The reasoning step between the two halves is the
agent's job, guided by SKILL.md.
"""
