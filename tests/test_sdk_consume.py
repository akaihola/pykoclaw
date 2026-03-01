"""Tests for the shared SDK response consumer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock
from claude_agent_sdk.types import StreamEvent

from pykoclaw.sdk_consume import consume_sdk_response


# ---------------------------------------------------------------------------
# Fake client stub (same pattern as pykoclaw-acp/tests/test_client_pool.py)
# ---------------------------------------------------------------------------


@dataclass
class FakeClient:
    """Stub ClaudeSDKClient whose receive_response yields canned messages."""

    messages: list[Any] = field(default_factory=list)
    _queried: str | None = None

    async def query(self, prompt: str) -> None:
        self._queried = prompt

    async def receive_response(self):  # noqa: ANN201
        for msg in self.messages:
            yield msg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result_msg(
    session_id: str = "sess-1",
    result: str = "",
) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=100,
        duration_api_ms=80,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        result=result,
    )


def _assistant_msg(*texts: str) -> AssistantMessage:
    return AssistantMessage(
        content=[TextBlock(text=t) for t in texts],
        model="test",
    )


def _tool_use_msg(tool_name: str = "Bash") -> AssistantMessage:
    """Create an AssistantMessage containing only a ToolUseBlock.

    The Claude Code SDK typically sends TextBlock and ToolUseBlock in
    *separate* single-block AssistantMessages rather than combining them.
    """
    return AssistantMessage(
        content=[
            ToolUseBlock(id="tool-1", name=tool_name, input={"command": "ls"}),
        ],
        model="test",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_blocks_forwarded() -> None:
    """Each non-empty TextBlock should trigger on_text exactly once."""
    client = FakeClient(
        messages=[
            _assistant_msg("Hello", "World"),
            _result_msg(result="Hello World"),
        ]
    )

    texts: list[str] = []
    result = await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["Hello", "World"]
    assert result is not None
    assert result.session_id == "sess-1"


@pytest.mark.asyncio
async def test_result_fallback_when_no_text_blocks() -> None:
    """When no TextBlocks are streamed, ResultMessage.result is forwarded."""
    client = FakeClient(messages=[_result_msg(result="Fallback text")])

    texts: list[str] = []
    result = await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["Fallback text"]
    assert result is not None


@pytest.mark.asyncio
async def test_no_duplication_with_text_blocks_and_result() -> None:
    """When TextBlocks ARE streamed, ResultMessage.result must NOT duplicate."""
    client = FakeClient(
        messages=[
            _assistant_msg("Streamed"),
            _result_msg(result="Streamed"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["Streamed"]


@pytest.mark.asyncio
async def test_on_text_none_no_crash() -> None:
    """Passing on_text=None must not raise."""
    client = FakeClient(
        messages=[
            _assistant_msg("Hello"),
            _result_msg(result="Hello"),
        ]
    )

    result = await consume_sdk_response(client, on_text=None)
    assert result is not None
    assert result.session_id == "sess-1"


@pytest.mark.asyncio
async def test_on_result_none_no_crash() -> None:
    """Passing on_result=None must not raise."""
    client = FakeClient(messages=[_result_msg(session_id="sess-2", result="text")])

    texts: list[str] = []
    result = await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
        on_result=None,
    )

    assert texts == ["text"]
    assert result is not None
    assert result.session_id == "sess-2"


@pytest.mark.asyncio
async def test_empty_text_block_skipped() -> None:
    """TextBlocks with empty text must NOT trigger on_text."""
    client = FakeClient(
        messages=[
            _assistant_msg("", "Real text", ""),
            _result_msg(result="Real text"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["Real text"]


@pytest.mark.asyncio
async def test_returns_result_message() -> None:
    """The return value must be the final ResultMessage."""
    expected = _result_msg(session_id="sess-ret", result="done")
    client = FakeClient(messages=[_assistant_msg("x"), expected])

    result = await consume_sdk_response(client)

    assert result is expected


@pytest.mark.asyncio
async def test_no_messages_returns_none() -> None:
    """An empty stream must return None."""
    client = FakeClient(messages=[])

    result = await consume_sdk_response(client)

    assert result is None


@pytest.mark.asyncio
async def test_on_result_called() -> None:
    """on_result must be called with the ResultMessage."""
    expected = _result_msg(session_id="sess-cb", result="reply")
    client = FakeClient(messages=[expected])

    results: list[ResultMessage] = []

    async def _on_result(msg: ResultMessage) -> None:
        results.append(msg)

    await consume_sdk_response(client, on_result=_on_result)

    assert results == [expected]


@pytest.mark.asyncio
async def test_result_fallback_not_sent_when_result_empty() -> None:
    """When result text is empty/falsy the fallback must NOT fire."""
    client = FakeClient(messages=[_result_msg(result="")])

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == []


@pytest.mark.asyncio
async def test_separator_inserted_between_tool_use_turns() -> None:
    """Text after a tool-use gap must be separated by a markdown horizontal rule.

    Without this, Mitto concatenates "I will do X:Good, now Y:" because
    the hidden tool call produces no visible text.  The "---" separator
    becomes an <hr/> which Mitto's coalescing logic uses to split into
    separate speech bubbles.

    The SDK sends TextBlock and ToolUseBlock as separate single-block
    AssistantMessages (verified empirically), so the test mirrors that.
    """
    client = FakeClient(
        messages=[
            _assistant_msg("I will do X:"),
            _tool_use_msg(),
            # UserMessage with tool result (ignored by consumer)
            _assistant_msg("Good, now Y:"),
            _tool_use_msg(),
            _assistant_msg("Final answer."),
            _result_msg(result="done"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == [
        "I will do X:",
        "\n\n---\n\n",
        "Good, now Y:",
        "\n\n---\n\n",
        "Final answer.",
    ]
    # Concatenated result should have horizontal-rule separators that
    # Mitto's coalescing logic turns into separate speech bubbles.
    assert (
        "".join(texts) == "I will do X:\n\n---\n\nGood, now Y:\n\n---\n\nFinal answer."
    )


@pytest.mark.asyncio
async def test_no_separator_without_tool_use() -> None:
    """Consecutive text-only AssistantMessages should NOT get separators.

    Only tool-use gaps trigger the separator.
    """
    client = FakeClient(
        messages=[
            _assistant_msg("Part one."),
            _assistant_msg("Part two."),
            _result_msg(result="done"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["Part one.", "Part two."]


@pytest.mark.asyncio
async def test_no_separator_when_first_message_has_tool_but_no_text() -> None:
    """A tool-use message with no preceding text should not produce a separator."""
    # This can happen when the agent jumps straight to a tool call with no
    # explanatory text first.
    client = FakeClient(
        messages=[
            _tool_use_msg(),
            _assistant_msg("Result after tool."),
            _result_msg(result="done"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    # No separator because no text was emitted before the tool-use message
    assert texts == ["Result after tool."]


# ---------------------------------------------------------------------------
# Streaming (StreamEvent / include_partial_messages=True) tests
# ---------------------------------------------------------------------------


def _stream_event(event: dict) -> StreamEvent:
    """Wrap a raw Anthropic stream event dict in a StreamEvent."""
    return StreamEvent(uuid="u1", session_id="sess-1", event=event)


def _cbs(idx: int) -> StreamEvent:
    """content_block_start for a text block at *idx*."""
    return _stream_event(
        {"type": "content_block_start", "index": idx, "content_block": {"type": "text"}}
    )


def _cbd(idx: int, text: str) -> StreamEvent:
    """content_block_delta with a text_delta for block at *idx*."""
    return _stream_event(
        {
            "type": "content_block_delta",
            "index": idx,
            "delta": {"type": "text_delta", "text": text},
        }
    )


def _cbe(idx: int) -> StreamEvent:
    """content_block_stop for block at *idx*."""
    return _stream_event({"type": "content_block_stop", "index": idx})


def _tool_cbs(idx: int) -> StreamEvent:
    """content_block_start for a tool_use block at *idx*."""
    return _stream_event(
        {
            "type": "content_block_start",
            "index": idx,
            "content_block": {"type": "tool_use", "id": "t1", "name": "Bash"},
        }
    )


def _msg_stop() -> StreamEvent:
    return _stream_event({"type": "message_stop"})


@pytest.mark.asyncio
async def test_streaming_deltas_forwarded() -> None:
    """StreamEvent text_delta tokens must each trigger on_text."""
    client = FakeClient(
        messages=[
            _cbs(0),
            _cbd(0, "Hello"),
            _cbd(0, ", "),
            _cbd(0, "world"),
            _cbe(0),
            _msg_stop(),
            _assistant_msg("Hello, world"),  # complete message — must be suppressed
            _result_msg(result="Hello, world"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    # Only the three deltas — not the redundant AssistantMessage TextBlock
    assert texts == ["Hello", ", ", "world"]


@pytest.mark.asyncio
async def test_streaming_no_double_emission() -> None:
    """AssistantMessage TextBlocks must be skipped when streaming was active."""
    client = FakeClient(
        messages=[
            _cbs(0),
            _cbd(0, "streamed"),
            _cbe(0),
            _msg_stop(),
            _assistant_msg("streamed"),  # would be a duplicate
            _result_msg(result="streamed"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["streamed"]
    assert texts.count("streamed") == 1


@pytest.mark.asyncio
async def test_streaming_result_fallback_not_duplicated() -> None:
    """ResultMessage.result must NOT be forwarded when streaming deltas fired."""
    client = FakeClient(
        messages=[
            _cbs(0),
            _cbd(0, "the answer"),
            _cbe(0),
            _msg_stop(),
            _assistant_msg("the answer"),
            _result_msg(result="the answer"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["the answer"]


@pytest.mark.asyncio
async def test_streaming_separator_between_tool_turns() -> None:
    """A tool-use block between two streaming text blocks must produce a separator."""
    client = FakeClient(
        messages=[
            # First text run
            _cbs(0),
            _cbd(0, "Before tool."),
            _cbe(0),
            _msg_stop(),
            _assistant_msg("Before tool."),
            # Tool use
            _tool_cbs(0),
            _cbe(0),
            _msg_stop(),
            _tool_use_msg(),
            # Second text run
            _cbs(0),
            _cbd(0, "After tool."),
            _cbe(0),
            _msg_stop(),
            _assistant_msg("After tool."),
            _result_msg(result="done"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["Before tool.", "\n\n---\n\n", "After tool."]


@pytest.mark.asyncio
async def test_streaming_non_text_delta_ignored() -> None:
    """Deltas for non-text blocks (e.g. tool input) must not reach on_text."""
    client = FakeClient(
        messages=[
            # Tool block — not a text block, so its deltas are ignored
            _stream_event(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "t1", "name": "Bash"},
                }
            ),
            _stream_event(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"cmd":'},
                }
            ),
            _cbe(0),
            # Real text block
            _cbs(1),
            _cbd(1, "Result."),
            _cbe(1),
            _msg_stop(),
            _assistant_msg("Result."),
            _result_msg(result="done"),
        ]
    )

    texts: list[str] = []
    await consume_sdk_response(
        client,
        on_text=lambda t: _append(texts, t),  # type: ignore[arg-type]
    )

    assert texts == ["Result."]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


async def _append(lst: list[str], value: str) -> None:
    lst.append(value)
