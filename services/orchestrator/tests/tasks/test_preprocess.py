"""Tests for the Swedish → English input preprocessing."""
import pytest

from preprocess import detect_language, maybe_translate, translate_to_english


# ── detect_language ────────────────────────────────────────────────────

def test_english_plain():
    assert detect_language("remind me to call mom at 5pm") == "en"


def test_english_with_names():
    assert detect_language("add milk to the shopping list") == "en"


def test_swedish_scand_chars():
    assert detect_language("påminn mig att köpa mjölk") == "sv"


def test_swedish_stopwords_only():
    # No å/ä/ö but plenty of Swedish function words
    assert detect_language("jag vill att du ska komma imorgon") == "sv"


def test_single_stopword_is_not_enough():
    # "ja" alone could be English-adjacent — require 2+ stopword hits
    assert detect_language("ja") == "en"


def test_empty_string():
    assert detect_language("") == "en"


def test_whitespace_only():
    assert detect_language("   ") == "en"


# ── translate_to_english ───────────────────────────────────────────────

async def _fake_llm_factory(response: str):
    async def fake_llm(messages, max_tokens):
        return response
    return fake_llm


async def test_translate_calls_llm_and_returns_result():
    fake = await _fake_llm_factory("remind me to buy milk")
    result = await translate_to_english("påminn mig att köpa mjölk", fake)
    assert result == "remind me to buy milk"


async def test_translate_strips_wrapping_quotes():
    fake = await _fake_llm_factory('"remind me to buy milk"')
    result = await translate_to_english("påminn mig att köpa mjölk", fake)
    assert result == "remind me to buy milk"


async def test_translate_returns_original_on_llm_failure():
    async def boom(messages, max_tokens):
        raise RuntimeError("ollama down")
    result = await translate_to_english("påminn mig", boom)
    assert result == "påminn mig"


async def test_translate_returns_original_on_empty_llm_response():
    fake = await _fake_llm_factory("")
    result = await translate_to_english("påminn mig", fake)
    assert result == "påminn mig"


# ── maybe_translate ────────────────────────────────────────────────────

async def test_maybe_translate_english_passthrough():
    async def llm(messages, max_tokens):
        raise AssertionError("LLM should not be called for English input")
    text, lang = await maybe_translate("remind me to call mom at 5pm", llm)
    assert text == "remind me to call mom at 5pm"
    assert lang == "en"


async def test_maybe_translate_swedish_invokes_llm():
    calls = []
    async def llm(messages, max_tokens):
        calls.append(messages)
        return "remind me to buy milk"
    text, lang = await maybe_translate("påminn mig att köpa mjölk", llm)
    assert text == "remind me to buy milk"
    assert lang == "sv"
    assert len(calls) == 1
