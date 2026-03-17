# Scheduled Task Output Modes

**Tags:** scheduler, channel-delivery, output-mode, ack-only
**Related:** [scheduled-task-design.md]

## Overview

`ScheduledTask.output_mode` controls how the scheduler delivers task results.
Two values are supported:

- `deliver_final` (default) — scheduler delivers the task's final reply to
  `target_conversation`.  The task must NOT send any channel messages itself.
- `ack_only` — the task sends the main summary to a target channel directly
  (e.g. via `send_whatsapp_message`, `send_matrix_message`, `send_slack_message`),
  and the task's final reply is only a short acknowledgement delivered by the
  scheduler.

## Where it lives

- `ScheduledTask.output_mode` field in `models.py`
- Column `output_mode TEXT DEFAULT 'deliver_final'` in `scheduled_tasks` table
- `create_task()` and `update_task()` in `db.py` accept and persist it
- `schedule_task` MCP tool exposes it as an optional parameter
- `schedule_channel_report_task` MCP tool selects the correct output contract
  template and appends it automatically

## Output contract templates

Defined as module-level constants in `tools.py`:

- `_OUTPUT_CONTRACT_DELIVER_FINAL` — appended for `deliver_final` tasks
- `_OUTPUT_CONTRACT_ACK_ONLY` — appended for `ack_only` tasks

Both suppress agent narration and enforce a single, well-defined final reply.

## Validation

`schedule_task` and `schedule_channel_report_task` warn (but do not block) when
`output_mode=ack_only` is requested but the prompt contains no recognised send
keywords (`send`, `post`, `deliver`, `dispatch`, `message`, `notify`, `write to`).

## Why `is_final` matters

`scheduler.py` uses `msg.is_final` to identify the SDK's final result message
and prefers it over the full transcript for delivery.  Prompts with the output
contract are still the primary defence — `is_final` is a second layer.

[scheduled-task-design.md]: scheduled-task-design.md
