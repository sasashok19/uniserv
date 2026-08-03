"""Guard tests for ASSISTANT_INSTRUCTIONS content (Feature 19).

Live-tested bug: after submit_complaint, the model's own closing
acknowledgement stated the ticket number/"registered" — duplicating the
separate automatic ack that app.notifications.sender.send_ticket_ack sends
once the complaint.ready pipeline actually creates the ticket. These are
plain string-content assertions rather than behavioural tests since
ASSISTANT_INSTRUCTIONS is a prompt, not code, but a silent revert of this
fix would be easy to miss otherwise.
"""

from app.conversation.tools import ASSISTANT_INSTRUCTIONS


def test_closing_acknowledgement_must_not_state_ticket_number_or_registration():
    assert "do NOT" in ASSISTANT_INSTRUCTIONS
    assert "ticket number" in ASSISTANT_INSTRUCTIONS
    assert "two confirmation" in ASSISTANT_INSTRUCTIONS


# Feature 20 guard: the two behaviours the live Assistant has to be told
# about, since neither is enforceable from code alone — what the citizen is
# shown, and what the model treats as a complaint.

def test_instructions_cover_the_email_typo_confirmation_round_trip():
    assert "did you mean" in ASSISTANT_INSTRUCTIONS
    assert "keeping BOTH spellings" in ASSISTANT_INSTRUCTIONS
    # The model must not "helpfully" apply the suggestion on the citizen's behalf.
    assert "Never substitute the suggested spelling" in ASSISTANT_INSTRUCTIONS


def test_instructions_forbid_treating_intake_answers_as_a_complaint():
    assert "only intake answers" in ASSISTANT_INSTRUCTIONS
    assert "never a complaint_summary" in ASSISTANT_INSTRUCTIONS
    # The exact live failure: the citizen's own email address recorded as the complaint.
    assert "never submit a name, an email address or an ID as the complaint_summary" in ASSISTANT_INSTRUCTIONS
