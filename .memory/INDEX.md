# Memory Index

Cross-reference index for `.memory/` files in `pykoclaw/`.

Each file documents one focused topic.  Keep files < 30 lines.

| File | Topic | Tags |
|------|-------|------|
| [claude-auto-memory-disabled.md] | `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` always set; why auto memory is disabled in SDK usage | claude-sdk, agent-core, memory |
| [scheduled-task-output-modes.md] | `output_mode` field: deliver_final vs ack_only, output contract templates, validation | scheduler, channel-delivery |
| [config-env-file-resolution.md] | `.env` load order: XDG config dir → $PYKOCLAW_DATA → CWD → env vars; platformdirs usage | config, pydantic-settings, XDG |

[claude-auto-memory-disabled.md]: claude-auto-memory-disabled.md
[scheduled-task-output-modes.md]: scheduled-task-output-modes.md
[config-env-file-resolution.md]: config-env-file-resolution.md
