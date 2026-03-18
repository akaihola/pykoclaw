# Claude Code Auto Memory — Disabled in SDK Usage

**Tags:** claude-sdk, agent-core, memory
**Related:** [INDEX.md]

Claude Code's auto-memory feature silently writes notes to
`~/.claude/projects/<project>/memory/MEMORY.md` during every session.
When the SDK is used as a library this contaminates the user's global
Claude memory store with pykoclaw-internal observations.

**Fix:** `agent_core._build_agent_env()` always sets
`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in the subprocess environment.
This disables auto memory only; CLAUDE.md instruction files still work.

**Alternatives (not used):**
- `autoMemoryEnabled: false` in settings JSON — same effect via `--settings`
- `--no-memory` CLI flag — also disables CLAUDE.md (too aggressive)

[INDEX.md]: INDEX.md
