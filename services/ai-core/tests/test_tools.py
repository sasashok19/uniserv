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


# Feature 22: the duplicate question is put to the CITIZEN, so both the tool
# and the instructions have to exist on the deployed Assistant — neither is
# enforceable from code alone.

def test_resolve_duplicate_tool_is_registered():
    from app.conversation.tools import ASSISTANT_TOOLS
    names = [t["function"]["name"] for t in ASSISTANT_TOOLS]
    assert "resolve_duplicate" in names
    schema = next(t for t in ASSISTANT_TOOLS if t["function"]["name"] == "resolve_duplicate")
    assert schema["function"]["parameters"]["required"] == ["isDuplicate"]


def test_instructions_tell_the_model_to_ask_before_merging():
    assert "Possible duplicate of an existing complaint" in ASSISTANT_INSTRUCTIONS
    assert "resolve_duplicate" in ASSISTANT_INSTRUCTIONS
    # It must ask, not decide — this is the whole point of the unclear verdict.
    assert "do not decide it yourself" in ASSISTANT_INSTRUCTIONS


# --- Feature 26 -----------------------------------------------------------
#
# The Assistant object lives on OpenAI's side and is shared by every tenant, so
# these clauses cannot be enforced from code — a silent revert would show up
# only as a citizen being told the wrong thing.

def test_the_assistant_never_names_a_hardcoded_company():
    """The welcome message is per-tenant; an assistant that calls itself
    "UniServe" to a TNEB citizen undoes the whole point of the config."""
    body = ASSISTANT_INSTRUCTIONS.split("Who you are speaking for:")[1]
    assert "company=" in body
    assert 'Never call yourself "UniServe"' in ASSISTANT_INSTRUCTIONS


def test_the_assistant_is_told_not_to_run_the_menu_itself():
    assert "do not present a menu" in ASSISTANT_INSTRUCTIONS
    assert "only ever invoked INSIDE option 2" in ASSISTANT_INSTRUCTIONS
    # The system appends the # line; the model doing it too reads as a stutter.
    assert 'do not say "type # for the main menu"' in ASSISTANT_INSTRUCTIONS


def test_the_assistant_may_never_invent_an_eta():
    """The ETA is a promise a human made. A model guessing "2-3 days" turns an
    unbacked guess into a commitment the citizen will hold us to."""
    assert "Never invent, estimate or imply a completion date" in ASSISTANT_INSTRUCTIONS
    assert "usually 2-3 days" in ASSISTANT_INSTRUCTIONS
    assert "only once a human has set one" in ASSISTANT_INSTRUCTIONS


def test_the_assistant_may_never_claim_to_change_a_tickets_state():
    assert "Never say you have reopened, resolved, closed, escalated or prioritised" \
        in ASSISTANT_INSTRUCTIONS


def test_the_assistant_handles_danger_before_anything_else():
    assert "immediate danger to life or property" in ASSISTANT_INSTRUCTIONS
    assert "keep away and contact the emergency helpline" in ASSISTANT_INSTRUCTIONS
    # Inventing a helpline number is worse than naming none.
    assert 'say "the emergency helpline" instead of inventing digits' in ASSISTANT_INSTRUCTIONS
    assert "Never advise a citizen to touch, repair, reconnect" in ASSISTANT_INSTRUCTIONS


def test_the_assistant_replies_in_the_citizens_language():
    assert "Reply in the language the citizen wrote in" in ASSISTANT_INSTRUCTIONS
    assert "Do not switch them to English" in ASSISTANT_INSTRUCTIONS


def test_the_assistant_covers_the_unactionable_message_cases():
    for clause in (
        "only an image, a document, an audio note",   # media with no text
        "several unrelated problems in one message",  # multi-complaint
        "greeting, a thank-you, or small talk",       # no complaint at all
        "do not have that information",               # out-of-scope questions
    ):
        assert clause in ASSISTANT_INSTRUCTIONS, clause


def test_the_assistant_stops_asking_the_duplicate_question_after_two_rounds():
    """Matches the code: app/dedup/confirmation.py allows exactly one round."""
    assert "Never ask the same distinguishing question three times" in ASSISTANT_INSTRUCTIONS


def test_the_assistant_stays_civil_with_an_angry_citizen():
    assert "Stay courteous if the citizen is angry or abusive" in ASSISTANT_INSTRUCTIONS
    assert "never threaten to end the conversation" in ASSISTANT_INSTRUCTIONS
