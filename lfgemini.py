"""Gemini helpers: ICP structuring, grounded lead discovery, sales assets."""
import json
import os
import re

from google import genai
from google.genai import types

import lf_verify as verify

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _ask(system, user, api_key=None, model=DEFAULT_MODEL, search=False, json_out=False):
    client = genai.Client(api_key=api_key or os.getenv("GEMINI_API_KEY"))
    cfg = {"system_instruction": system, "temperature": 0.4 if search else 0.7}
    if search:
        cfg["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    if json_out:
        cfg["response_mime_type"] = "application/json"
    resp = client.models.generate_content(
        model=model, contents=user, config=types.GenerateContentConfig(**cfg))
    return (resp.text or "").strip()


def extract_json(text):
    text = re.sub(r"```(?:json)?", "", text).strip()
    starts = [i for i in (text.find("["), text.find("{")) if i != -1]
    if not starts:
        raise ValueError("No JSON in model output")
    return json.loads(text[min(starts): max(text.rfind("]"), text.rfind("}")) + 1])


def brief_to_icp(brief, api_key=None, model=DEFAULT_MODEL):
    system = "You turn a client's lead-list request into a precise Ideal Customer Profile. Return ONLY JSON."
    user = f"""Client request:\n{brief}\n
Return JSON: {{"industry": str, "geography": str, "company_size": str,
"target_titles": [str], "must_have_signals": [str], "exclusions": [str],
"search_keywords": [str], "summary": str}}"""
    return extract_json(_ask(system, user, api_key, model, json_out=True))


def discover_batch(icp, exclude_domains, k=8, api_key=None, model=DEFAULT_MODEL):
    """Find real companies + one publicly listed decision-maker each, with source URLs."""
    system = (
        "You are a careful B2B researcher. Use Google Search. Only report people whose NAME and TITLE "
        "are publicly displayed on the company's own website (team/about/leadership page) or an official "
        "press page. NEVER guess or infer names or emails. Include an email ONLY if it is literally shown "
        "on that page (business address); otherwise use an empty string. Return ONLY a JSON array."
    )
    user = f"""ICP:\n{json.dumps(icp, indent=2)}

Find up to {k} DIFFERENT companies that match. Skip these domains: {sorted(exclude_domains)[:150]}

JSON array items:
{{"company": str, "website": "https://...", "contact_name": str, "title": str,
  "email": "only if shown publicly else empty", "country": str,
  "source_url": "exact page URL where the person is listed", "why_fit": str}}"""
    return extract_json(_ask(system, user, api_key, model, search=True))


def sales_assets(focus, api_key=None, model=DEFAULT_MODEL):
    system = "You are a B2B direct-response copywriter. Be specific, honest, no hype. Markdown output."
    user = f"""Business: LeadForge — custom, human-verified B2B lead lists for niche markets. Every contact is
checked against its public source, delivered with a source URL, and refreshed monthly on request.
Compete against Apollo (cheap but stale) and agencies ($2k-15k/mo retainers).
Our focus niche: {focus}

Write:
1. Landing page copy (headline, subhead, 3 benefits, how it works in 4 steps, pricing section, FAQ of 6, CTA)
2. Offer + guarantee (e.g. free 10-lead sample, replace any bad contact within 14 days)
3. Three cold emails (different angles, under 110 words each) + 2 follow-ups
4. Two LinkedIn DM variants (under 60 words)
5. Six objection handlers (price, "we use Apollo", data accuracy, GDPR, trust, timing)
6. A 30-day outreach plan (daily volume, channels, metrics)
Every email must include an opt-out line and sender identification (CAN-SPAM / GDPR-friendly)."""
    return _ask(system, user, api_key, model)


def domain_set(leads):
    return {verify.domain_of(l.get("website", "")) for l in leads if l.get("website")}
