"""Shared SDK response consumption — single source of truth for iterating
``ClaudeSDKClient.receive_response()`` and extracting text / result messages.

Both ``query_agent()`` (WhatsApp / scheduler) and ``ClientPool._query()``
(ACP / Mitto) delegate to :func:`consume_sdk_response` so that fallback
logic and message handling stay in one place.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from claude_agent_sdk.types import StreamEvent


async def consume_sdk_response(
    client: ClaudeSDKClient,
    *,
    on_text: Callable[[str], Awaitable[None]] | None = None,
    on_result: Callable[[ResultMessage], Awaitable[None]] | None = None,
) -> ResultMessage | None:
    """Iterate *client*.receive_response() and dispatch to callbacks.

    Streaming mode (``include_partial_messages=True``):
    * ``StreamEvent`` objects with ``content_block_delta`` / ``text_delta``
      events drive *on_text* for incremental token delivery.
    * The subsequent complete ``AssistantMessage`` is still emitted by the
      SDK but we skip its ``TextBlock.text`` calls to avoid double-emission.

    Non-streaming mode (``include_partial_messages=False``, default):
    * For each ``AssistantMessage``, every non-empty ``TextBlock.text`` is
      forwarded to *on_text* as before.

    In both modes:
    * For ``ResultMessage``: if **no** text was seen and ``message.result``
      is truthy, *on_text* is called with the result text as a fallback
      (prevents silent replies).  *on_result* is always called when provided.
    * Returns the final ``ResultMessage``, or ``None`` when the stream
      contained no messages.

    Tool-use separator:
    When the agent produces text, then uses a tool, then produces more text,
    the two text runs would otherwise be concatenated without any whitespace
    (e.g. "I will do X:Good, now Y:").  A markdown horizontal rule ("---")
    is emitted between the two runs — this creates a visual bubble break in
    Mitto (whose coalescing logic splits on <hr/>) and a clear section
    separator for other consumers.
    """
    had_text = False
    # True when a ToolUse came after the last text run — cleared when the
    # next text content starts.
    pending_separator = False

    # True when at least one StreamEvent text_delta was emitted for the
    # current response.  When set, the matching AssistantMessage TextBlocks
    # are skipped to prevent double-emission.
    streaming_active = False

    # Track the content block index for which a content_block_start with
    # type "text" was seen, so we only emit deltas for text blocks.
    _active_text_block_indices: set[int] = set()

    final_result: ResultMessage | None = None

    async for message in client.receive_response():
        if isinstance(message, StreamEvent):
            event = message.event
            event_type = event.get("type")

            if event_type == "content_block_start":
                block = event.get("content_block", {})
                if block.get("type") == "text":
                    idx = event.get("index", -1)
                    _active_text_block_indices.add(idx)
                elif block.get("type") == "tool_use" and had_text:
                    # Tool call starting after we've seen some text — mark
                    # that a separator should precede the next text chunk.
                    pending_separator = True

            elif event_type == "content_block_delta":
                idx = event.get("index", -1)
                if idx in _active_text_block_indices:
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        if text and on_text is not None:
                            if pending_separator:
                                await on_text("\n\n---\n\n")
                                pending_separator = False
                            await on_text(text)
                            had_text = True
                            streaming_active = True

            elif event_type == "content_block_stop":
                idx = event.get("index", -1)
                _active_text_block_indices.discard(idx)

            elif event_type == "message_stop":
                # Clear block index tracking; streaming_active stays True until
                # the matching AssistantMessage is consumed and suppressed.
                _active_text_block_indices.clear()

        elif isinstance(message, AssistantMessage):
            if streaming_active:
                # Deltas already drove on_text — skip TextBlocks to avoid
                # double-emission, but still detect tool-use gaps.
                for block in message.content:
                    if isinstance(block, ToolUseBlock) and had_text:
                        pending_separator = True
                # Reset now, after consuming this message, so the next turn
                # (after a tool round-trip) can stream again.
                streaming_active = False
            else:
                # Non-streaming path: emit complete TextBlocks as before.
                for block in message.content:
                    if isinstance(block, TextBlock) and block.text:
                        if on_text is not None:
                            if pending_separator:
                                await on_text("\n\n---\n\n")
                                pending_separator = False
                            await on_text(block.text)
                        had_text = True
                    elif isinstance(block, ToolUseBlock) and had_text:
                        # The SDK typically sends TextBlock and ToolUseBlock
                        # in separate single-block AssistantMessages, so we
                        # check per-block rather than per-message.
                        pending_separator = True

        elif isinstance(message, ResultMessage):
            final_result = message

            # Fallback: forward ResultMessage.result when no text was
            # streamed so the caller still sees the reply.
            if not had_text and message.result and on_text is not None:
                await on_text(message.result)

            if on_result is not None:
                await on_result(message)

    return final_result
