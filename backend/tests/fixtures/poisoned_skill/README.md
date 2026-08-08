# Poisoned skill (test fixture)

A deliberately malicious agent skill used only to verify detection. Never executed.

Expected detections:
- prompt injection with concealment ("do not tell the user")
- credential exfiltration instructions
- remote code execution via curl-pipe-to-shell
