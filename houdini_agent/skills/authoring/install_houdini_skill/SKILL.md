---
{"name":"install_houdini_skill","category":"authoring","description":"Preview or install reviewed Houdini-Agent Skill source, or explicitly activate an installed user Skill. Installation never imports the source; activation imports it after confirmation.","risk_level":"high","parameters":{"skill_source":{"type":"string","description":"Deprecated legacy source; standard installs use skill_files.","required":false},"skill_files":{"type":"object","description":"Reviewed bundle files: SKILL.md and scripts/main.py.","required":false},"mode":{"type":"string","description":"Compatibility alias for action: preview or install.","required":false,"default":"preview"},"action":{"type":"string","description":"preview, install, or activate.","required":false},"skill_name":{"type":"string","description":"Installed Skill name required for activate.","required":false}},"entrypoint":"scripts/main.py:run"}
---
# Install Houdini Skill

按照参数合同执行此 Skill；保持返回结构与既有行为不变。
