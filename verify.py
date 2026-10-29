"""Lead verification: proves each lead against its public source page.

Checks (no SMTP probing, no private data): source page reachable, person's name
and title appear on it, email syntax + MX record, email literally on the page,
disposable/role-address flags. Produces a 0-100 confidence score.
"""
import re
from urllib.parse import urlparse

import requests

try:
    import dns.resolver
except ImportError:  # pragma: no cover
    dns = None

EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$")
FIND_EMAILS = re.compile(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}")
DISPOSABLE = {"mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com",
              "yopmail.com", "trashmail.com", "sharklasers.com"}
ROLE_PREFIXES = {"info", "sales", "contact", "admin", "support", "hello", "office",
                 "team", "help", "noreply", "no-reply"}
UA = {"User-Agent": "Mozilla/5.0 (compatible; LeadForgeVerifier/1.0)"}


def valid_syntax(email):
    return bool(EMAIL_RE.match((email or "").strip().lower()))


def domain_of(value):
    value = (value or "").strip().lower()
    if "@" in value:
        return value.split("@", 1)[1]
    if "://" not in value:
        value = "http://" + value
    host = urlparse(value).netloc
    return host[4:] if host.startswith("www.") else host


def has_mx(domain):
    if not domain or dns is None:
        return False
    try:
        return len(dns.resolver.resolve(domain, "MX", lifetime=5)) > 0
    except Exception:
        return False


def fetch_text(url):
    """Return lowercased visible-ish text of a page, or None if unreachable."""
    if not url:
        return None
    try:
        r = requests.get(url, headers=UA, timeout=10)
        if r.status_code >= 400:
            return None
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", r.text)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).lower()
    except Exception:
        return None


def check_lead(lead, fetch=None, mx=None):
    """Return dict(confidence, status, flags, notes, email)."""
    fetch = fetch or fetch_text
    mx = mx or has_mx
    score, flags, notes = 0, [], ""
    email = (lead.get("email") or "").strip().lower()
    page = fetch(lead.get("source_url") or "")

    if page:
        score += 30
    else:
        flags.append("source_unreachable")

    tokens = [t for t in re.findall(r"[^\W\d_]+", (lead.get("contact_name") or "").lower()) if len(t) > 1]
    if page and tokens and tokens[0] in page and tokens[-1] in page:
        score += 30
    else:
        flags.append("name_not_on_source")

    title = (lead.get("title") or "").strip().lower()
    if page and title and title in page:
        score += 10
    else:
        flags.append("title_not_on_source")

    if email:
        if not valid_syntax(email):
            flags.append("bad_email_syntax")
            email = ""
        else:
            edomain = domain_of(email)
            if page and email in page:
                score += 20
            else:
                flags.append("email_not_on_source")
            if mx(edomain):
                score += 10
            else:
                flags.append("no_mx_record")
            if edomain in DISPOSABLE:
                flags.append("disposable_domain")
                score -= 30
            if email.split("@")[0] in ROLE_PREFIXES:
                flags.append("role_email")
    else:
        flags.append("no_email")
        if page:
            seen = sorted(set(FIND_EMAILS.findall(page)))[:3]
            if seen:
                notes = "Emails seen on source page (unassigned): " + ", ".join(seen)

    score = max(0, min(100, score))
    # A person's name must appear on the source page, otherwise a human must check.
    ok = score >= 70 and email and "name_not_on_source" not in flags and "source_unreachable" not in flags
    status = "auto_verified" if ok else "needs_review"
    return {"confidence": score, "status": status, "flags": ",".join(flags),
            "notes": notes, "email": email}
