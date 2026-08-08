# Poisoned MCP server (test fixture)

A deliberately malicious MCP server used only to verify that the governance scanners detect
what they are supposed to detect. It is never executed — the scanners read source.

Expected detections:
- tool description / behaviour mismatch (data exfiltration)
- prompt injection concealed in a tool docstring
- dependency CVEs from the pinned requirements
