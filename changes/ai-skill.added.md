- `pyfect.ai.skill` (Effect's `effect/ai/Skill`): an Agent Skill as a value. `skill.make`
  checks the frontmatter and file paths, `to_files` writes it as a `SKILL.md` and its
  files, and `from_files` reads one back, failing with `IllegalArgumentError`. Its JSON
  codec keeps a file's bytes as `{"base64": ...}`. `mcp_server.skill` and
  `mcp_server.register_skill` take a `Skill` in place of the files.
