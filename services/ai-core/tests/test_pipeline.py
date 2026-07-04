"""Unit tests for the rule-based AI pipeline (Features 07, 08, 10)."""

from app.classify.classifier import classify
from app.pii.scrubber import scrub_text
from app.priority.engine import ScoreRequest, label_for, score


def test_priority_high_severity_scores_critical():
    req = ScoreRequest(
        tenantId="t1", sentimentScore=-0.85, slaHoursRemaining=1.5, slaHoursTotal=48,
        repeatContactCount=2, categoryLabel="outage", channel="whatsapp",
        vulnerabilityKeywordsFound=["emergency"])
    result = score(req)
    assert result["label"] == "critical"
    assert result["score"] >= 8.0


def test_priority_labels():
    assert label_for(9.0) == "critical"
    assert label_for(6.5) == "high"
    assert label_for(4.2) == "medium"
    assert label_for(1.0) == "low"


def test_classify_billing_complaint():
    result = classify("My electricity bill for March is double the usual amount. Second time this happened.")
    assert result["category"] == "billing"
    assert result["confidence"] >= 0.7
    assert result["sentimentScore"] < 0
    assert result["intent"] == "complaint"


def test_classify_ambiguous_is_other_low_confidence():
    result = classify("Something is wrong")
    assert result["category"] == "other"
    assert result["confidence"] < 0.5


def test_pii_scrub_detects_person_phone_aadhaar():
    text = "My name is Rajesh Kumar, phone +91 98765 43210, Aadhaar 1234 5678 9012"
    scrubbed, entities, token_map = scrub_text(text)
    assert "[PERSON_1]" in scrubbed
    assert "[PHONE_1]" in scrubbed
    assert "[IN_AADHAAR_1]" in scrubbed
    assert entities == ["PERSON", "PHONE_NUMBER", "IN_AADHAAR"]
    assert len(token_map) == 3
    assert token_map["[PERSON_1]"] == "Rajesh Kumar"
