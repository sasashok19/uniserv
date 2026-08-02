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
