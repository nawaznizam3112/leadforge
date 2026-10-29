import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import verify  # noqa: E402

PAGE = "our team: jane doe, head of it. contact jane.doe@acme.com for details"


def lead(**kw):
    base = dict(contact_name="Jane Doe", title="Head of IT", email="jane.doe@acme.com",
                source_url="https://acme.com/team")
    base.update(kw)
    return base


def test_syntax_and_domain():
    assert verify.valid_syntax("a@b.co")
    assert not verify.valid_syntax("not-an-email")
    assert verify.domain_of("https://www.acme.com/team") == "acme.com"
    assert verify.domain_of("x@acme.com") == "acme.com"


def test_full_verification():
    r = verify.check_lead(lead(), fetch=lambda u: PAGE, mx=lambda d: True)
    assert r["confidence"] == 100 and r["status"] == "auto_verified"


def test_hallucinated_person_fails():
    r = verify.check_lead(lead(contact_name="John Smith"), fetch=lambda u: PAGE, mx=lambda d: True)
    assert "name_not_on_source" in r["flags"] and r["status"] == "needs_review"


def test_unreachable_source():
    r = verify.check_lead(lead(), fetch=lambda u: None, mx=lambda d: True)
    assert "source_unreachable" in r["flags"] and r["status"] == "needs_review"


def test_no_email_never_auto_verified():
    r = verify.check_lead(lead(email=""), fetch=lambda u: PAGE, mx=lambda d: True)
    assert r["status"] == "needs_review" and "no_email" in r["flags"]


def test_disposable_and_role():
    r = verify.check_lead(lead(email="info@mailinator.com"), fetch=lambda u: PAGE, mx=lambda d: True)
    assert "disposable_domain" in r["flags"] and "role_email" in r["flags"]
