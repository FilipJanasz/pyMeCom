# Automation workflow (transport split)

This workflow separates transport-specific automation artifacts so COM and TCP work can evolve independently.

- `workflows/automation/com`: serial/COM working baseline
- `workflows/automation/tcp`: TCP migration scaffold
- `workflows/automation/common`: transport-agnostic shared files
