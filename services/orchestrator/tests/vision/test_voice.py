import pytest

from integrations.vision.voice import reword, VOICE_PROMPT_TEMPLATE


async def test_reword_calls_llm_with_context():
    seen = {}
    async def fake_llm(messages, max_tokens):
        seen["messages"] = messages
        seen["max_tokens"] = max_tokens
        return "Mmm, the afternoon light is gorgeous on your plant."

    result = await reword(
        raw="A potted plant on a sunlit windowsill.",
        user_question="what do you see?",
        llm_chat=fake_llm,
    )
    assert result == "Mmm, the afternoon light is gorgeous on your plant."
    prompt = seen["messages"][0]["content"]
    assert "A potted plant on a sunlit windowsill." in prompt
    assert "what do you see?" in prompt
    assert seen["max_tokens"] == 150


async def test_reword_returns_raw_on_llm_exception():
    async def broken_llm(messages, max_tokens):
        raise RuntimeError("llm down")

    raw = "A cluttered desk with a laptop."
    result = await reword(raw=raw, user_question="what do you see?", llm_chat=broken_llm)
    assert result == raw


async def test_reword_returns_raw_on_empty_llm_response():
    async def empty_llm(messages, max_tokens):
        return "   "

    raw = "An empty room."
    result = await reword(raw=raw, user_question="what do you see?", llm_chat=empty_llm)
    assert result == raw


async def test_reword_strips_wrapping_quotes():
    async def quote_llm(messages, max_tokens):
        return '"Mmm, I see it."'

    result = await reword(
        raw="A thing.", user_question="see?", llm_chat=quote_llm
    )
    assert result == "Mmm, I see it."
