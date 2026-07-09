"""Unit tests for LLM extraction with mock mode."""
import os
import pytest

os.environ["LLM_MOCK"] = "true"

import asyncio
from app.memory.extract import extract_career_facts


@pytest.mark.asyncio
async def test_extract_returns_dict():
    result = await extract_career_facts("I am a software engineer with 5 years Python experience.")
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_extract_empty_returns_empty():
    result = await extract_career_facts("")
    assert result == {}


@pytest.mark.asyncio
async def test_extract_whitespace_returns_empty():
    result = await extract_career_facts("   \n  ")
    assert result == {}


@pytest.mark.asyncio
async def test_mock_does_not_raise():
    # With LLM_MOCK=true the function should never raise regardless of input.
    result = await extract_career_facts("Some random text that might trip up a real LLM.")
    assert result is not None
