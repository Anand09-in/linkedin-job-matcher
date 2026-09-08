"""Unit tests for synthesize_referral_contacts — LLM call mocked. No
Postgres, no Bedrock, no web search needed."""
from __future__ import annotations

from app.llm_tasks.referral_synthesis import synthesize_referral_contacts
from app.llm_tasks.schemas import ReferralContact, ReferralSearchResult


class _FakeStructuredLLM:
    def __init__(self, response: ReferralSearchResult):
        self._response = response

    async def ainvoke(self, messages):
        return self._response


class _FakeLLM:
    def __init__(self, response: ReferralSearchResult):
        self._response = response

    def with_structured_output(self, schema):
        return _FakeStructuredLLM(self._response)


async def test_synthesize_referral_contacts_returns_llm_result():
    fake = ReferralSearchResult(
        contacts=[
            ReferralContact(name="Jane Doe", title="Software Engineer at Acme", profile_url="https://linkedin.com/in/janedoe"),
        ],
        caveat="Public search snapshot — verify current employment before reaching out.",
    )

    result = await synthesize_referral_contacts(
        company="Acme", job_title="Data Engineer",
        search_results_text="[Jane Doe - Software Engineer at Acme]: ... (https://linkedin.com/in/janedoe)",
        llm=_FakeLLM(fake),
    )

    assert len(result.contacts) == 1
    assert result.contacts[0].name == "Jane Doe"
    assert result.caveat


async def test_synthesize_referral_contacts_empty_results_returns_empty_list():
    """No real people found in search results -> empty list, not fabricated
    contacts (the prompt explicitly forbids inventing plausible names)."""
    fake = ReferralSearchResult(contacts=[], caveat="No relevant public profiles found.")

    result = await synthesize_referral_contacts(
        company="Totally Obscure Co", job_title="Engineer", search_results_text="", llm=_FakeLLM(fake),
    )

    assert result.contacts == []
