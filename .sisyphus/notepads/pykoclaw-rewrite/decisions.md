# Decisions

## Session Resume Validation (Wave 1)

### Finding: Session Resume NOT Working in Python SDK

**Status**: BROKEN - Resume parameter is passed to CLI but fails with error

**Test Results**:
- ✅ CLI (`claude --resume <session-id>`) works correctly - session is resumed and context is preserved
- ❌ Python SDK (`ClaudeSDKClient(options=ClaudeAgentOptions(resume=session_id))`) fails - returns error_during_execution

**Evidence**:
1. CLI test (bash script) successfully resumed session and Claude remembered "PELICAN42"
2. Python SDK test returns `ResultMessage(is_error=True, subtype='error_during_execution', result=None)`
3. SDK correctly passes `--resume <session-id>` flag to CLI subprocess
4. Error details not exposed in SDK (ResultMessage doesn't include errors field)

**Root Cause Analysis**:
- The SDK passes the resume flag correctly to the CLI
- The CLI subprocess is being invoked with proper arguments
- The error occurs at the CLI level, not the SDK wrapper
- Likely issue: Session persistence or session lookup in Claude Code CLI

**Session Storage Location**:
- Sessions stored in: `~/.claude/projects/<project-hash>/`
- Files: `<session-id>.jsonl` (contains queue operations)
- Sessions are per-project (based on working directory)

**Implications for pykoclaw**:
- Cannot rely on `resume` parameter for cross-process session persistence
- Multi-turn conversations must happen within same client instance
- Session context is lost when client disconnects
- Need alternative approach for persistent agent state

**Next Steps**:
- Investigate Claude Code CLI version compatibility
- Check if resumeSessionAt parameter (used in nanoclaw) is needed
- Consider implementing session state persistence at application level
