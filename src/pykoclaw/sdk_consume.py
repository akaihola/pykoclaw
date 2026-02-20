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
)


async def consume_sdk_response(
    client: ClaudeSDKClient,
    *,
    on_text: Callable[[str], Awaitable[None]] | None = None,
    on_result: Callable[[ResultMessage], Awaitable[None]] | None = None,
) -> ResultMessage | None:
    """Iterate *client*.receive_response() and dispatch to callbacks.

    * For each ``AssistantMessage``, every non-empty ``TextBlock.text`` is
      forwarded to *on_text*.
    * For ``ResultMessage``: if **no** text blocks were seen and
      ``message.result`` is truthy, *on_text* is called with the result
      text as a fallback (prevents silent replies).  *on_result* is always
      called when provided.
    * Returns the final ``ResultMessage``, or ``None`` when the stream
      contained no messages.
    """
    had_text_blocks = False
    final_result: ResultMessage | None = None

    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text:
                    had_text_blocks = True
                    if on_text is not None:
                        await on_text(block.text)

        elif isinstance(message, ResultMessage):
            final_result = message

            # Fallback: forward ResultMessage.result when no TextBlock
            # was streamed so the caller still sees the reply.
            if not had_text_blocks and message.result and on_text is not None:
                await on_text(message.result)

            if on_result is not None:
                await on_result(message)

    return final_result
