"""The WhatsApp conversation menu (Feature 26).

Walks the state machine the way a citizen walks it: welcome, pick an option,
answer, get an answer back. The assertions people will care about are the ones
about what must NOT happen — no ticket created for a status enquiry, no other
citizen's ticket readable by guessing its number, no acknowledgement of a note
that was never written.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from app.conversation import menu, menu_content


def _run(coro):
    return asyncio.run(coro)


TENANT = "t1"
THREAD = "whatsapp:+919876543210"
PHONE = "+919876543210"


def _db(ticket=None, identity=None, tickets=None):
    db = MagicMock()
    db.list_tickets = AsyncMock(return_value=tickets if tickets is not None else ([ticket] if ticket else []))
    db.get_ticket = AsyncMock(return_value=ticket)
    db.find_by_phone = AsyncMock(return_value=identity)
    db.add_message = AsyncMock(return_value={"id": "m-1"})
    db.add_event = AsyncMock(return_value={"id": "e-1"})
    db.create_ticket = AsyncMock(return_value={"id": "new-1", "ticketNumber": "TKT-00099"})
    return db


def _ticket(**overrides):
    ticket = {
        "id": "t-1",
        "ticket_number": "TKT-00042",
        "status": "in_progress",
        "eta_at": "2026-08-18 23:59:59",
        "updated_at": "2026-08-15 04:00:00",
        "identity_id": "master-1",
        "thread_id": THREAD,
    }
    ticket.update(overrides)
    return ticket


def _handle(db, text, tenant_config=None, thread=THREAD):
    return _run(menu.handle_inbound(
        db, TENANT, thread, text, identity_value=PHONE,
        tenant_config=tenant_config if tenant_config is not None else {}))


def _is_main_menu(message):
    """The menu is the menu whether it arrives as buttons or as "Press 1"."""
    if message.buttons:
        return len(message.buttons) == 3
    return all(x in message.text for x in ("Press 1", "Press 2", "Press 3"))


def _button_titles(message):
    return [b["title"] for b in (message.buttons or [])]


# --- first contact ---------------------------------------------------------

def test_the_ai_speaks_first_with_the_company_name_and_the_three_options(fake_valkey):
    out = _handle(_db(), "hi", {"landingPage": {"brandName": "TNEB"}})

    assert out.stop is True
    message = out.replies[0]
    assert "Welcome to TNEB" in message.text
    # Feature 28: the three options are tappable buttons, not "press 1" text.
    assert _button_titles(message) == ["Ticket status", "New ticket", "End chat"]
    assert [b["id"] for b in message.buttons] == ["menu_1", "menu_2", "menu_3"]
    # The # escape moves to the footer, where WhatsApp renders it under the buttons.
    assert "#" in (message.footer or "")
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


def test_the_options_fall_back_to_numbered_text_when_buttons_are_off(fake_valkey):
    """A tenant can opt out, and then the body must carry the options itself."""
    out = _handle(_db(), "hi", {"whatsappMenu": {"useInteractiveButtons": False}})

    message = out.replies[0]
    assert message.buttons is None
    assert all(x in message.text for x in ("Press 1", "Press 2", "Press 3"))
    assert "#" in message.text


def test_button_titles_stay_within_metas_twenty_character_cap(fake_valkey):
    """Meta rejects the whole send if a title is too long, so the citizen would
    get nothing at all — clamped on the way out as well as on save."""
    out = _handle(_db(), "hi", {"whatsappMenu": {
        "option1Label": "Check the status of an existing ticket please"}})

    assert all(len(t) <= menu.BUTTON_TITLE_MAX for t in _button_titles(out.replies[0]))


def test_a_tapped_button_is_matched_by_its_configured_label(fake_valkey):
    """Meta delivers a tap as the button's TITLE, and titles are tenant-
    configurable — so matching cannot rely on a fixed English word list."""
    config = {"whatsappMenu": {"option2Label": "Pukaar darj karein"}}
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "Pukaar darj karein", config)

    assert "register a new ticket" in out.replies[0].text.lower()


def test_the_company_name_is_configurable_independently_of_the_brand(fake_valkey):
    out = _handle(_db(), "hi", {"landingPage": {"brandName": "TNEB"},
                                "whatsappMenu": {"companyName": "TNEB Customer Care"}})
    assert "Welcome to TNEB Customer Care" in out.replies[0].text


def test_a_first_message_that_is_a_complaint_is_kept_not_discarded(fake_valkey):
    """The citizen still gets the menu, but must never be made to retype."""
    _handle(_db(), "Power cut in Madambakkam")

    session = json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])
    assert session["carryOver"] == "Power cut in Madambakkam"


def test_a_bare_menu_key_is_not_carried_over_as_a_complaint(fake_valkey):
    _handle(_db(), "2")
    session = json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])
    assert "carryOver" not in session, '"2" is a menu key, not a complaint'


# --- option 3 --------------------------------------------------------------

def test_option_three_says_goodbye_and_ends_the_session(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "3")

    assert [m.text for m in out.replies] == ["Thanks for reaching out. Have a great time"]
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store
    # No "press # for the menu" here: the conversation is over, and offering a
    # way back into a menu we just closed contradicts the goodbye.
    assert "#" not in out.replies[0].text


def test_a_message_after_the_chat_ended_re_opens_the_main_menu(fake_valkey):
    out = _handle(_db(), "hello again")
    assert _is_main_menu(out.replies[0])


# --- option 1: status, ETA, last updated -----------------------------------

def test_option_one_asks_for_the_ticket_id(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "1")

    assert "Ticket ID" in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_ticket_id"


def test_a_ticket_id_returns_that_one_ticket_with_status_eta_and_last_updated(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    text = out.replies[0].text
    assert "TKT-00042" in text
    assert "Work in progress" in text
    assert "18 Aug 2026" in text      # the ETA
    assert "15 Aug 2026" in text      # last updated
    assert "#" in text


def test_only_that_one_ticket_is_reported_not_the_citizens_whole_list(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert "TKT-00043" not in out.replies[0].text
    # The lookup is BY NUMBER, not "list everything this identity owns".
    assert db.list_tickets.await_args.kwargs["ticketNumber"] == "TKT-00042"


def test_a_bare_number_is_accepted_as_a_ticket_id(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    _handle(db, "42")

    assert db.list_tickets.await_args.kwargs["ticketNumber"] == "TKT-00042"


def test_a_ticket_belonging_to_someone_else_is_reported_as_not_found(fake_valkey):
    """Ticket numbers are sequential and guessable, so without an ownership
    check anyone could read any citizen's complaint status by counting. Saying
    "that ticket isn't yours" would itself confirm it exists."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(identity_id="someone-else", thread_id="whatsapp:+910000000000"),
             identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert "couldn't find" in out.replies[0].text
    assert "TKT-00042" not in out.replies[0].text.replace("TKT-00042)", "")
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_ticket_id"


def test_an_unknown_ticket_id_re_asks_rather_than_dropping_the_citizen(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(tickets=[])

    out = _handle(db, "TKT-99999")

    assert "couldn't find" in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_ticket_id"


def test_a_ticket_with_no_eta_says_so_rather_than_showing_a_blank(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(eta_at=None), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert "not set yet" in out.replies[0].text


def test_a_status_enquiry_never_creates_a_ticket(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert out.stop is True, "option 1 must never reach the ticket-creating pipeline"
    db.create_ticket.assert_not_awaited()


# --- option 1: dropping a note ---------------------------------------------

def test_the_details_message_invites_a_note(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert "add" in out.replies[0].text.lower()
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_note"


def test_a_note_lands_on_the_ticket_and_ends_the_conversation(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps(
        {"state": "await_note", "ticketId": "t-1", "ticketNumber": "TKT-00042"})
    db = _db(ticket=_ticket())

    out = _handle(db, "The power is still off after 3 days")

    _, payload = db.add_message.await_args.args
    assert payload["content"] == "The power is still off after 3 days"
    assert payload["direction"] == "inbound" and payload["authorType"] == "user"
    # Findable as a citizen-initiated addition, not just another inbound line.
    assert db.add_event.await_args.args[1]["eventType"] == "ticket.citizen_note"

    assert "TKT-00042" in out.replies[0].text
    assert "team will revert" in out.replies[0].text
    assert "main menu will open again" in out.replies[1].text
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store


def test_a_note_that_could_not_be_saved_is_never_acknowledged(fake_valkey):
    """Telling a citizen "the team will revert" about a note that does not
    exist is the one outcome here worse than an error message."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps(
        {"state": "await_note", "ticketId": "t-1", "ticketNumber": "TKT-00042"})
    db = _db(ticket=_ticket())
    db.add_message = AsyncMock(side_effect=RuntimeError("db down"))

    out = _handle(db, "still broken")

    assert "team will revert" not in out.replies[0].text
    assert f"wamenu:{TENANT}:{THREAD}" in fake_valkey.store, "the citizen may retry"


# --- option 2 --------------------------------------------------------------

def test_option_two_lists_the_details_needed_and_hands_off_to_intake(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "2")

    assert "register a new ticket" in out.replies[0].text.lower()
    # The tenant's configured intake form, not a hardcoded list.
    assert "1." in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "intake"


def test_option_two_does_not_ask_for_the_phone_number_whatsapp_already_gave_us(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "2")

    assert "Mobile" not in out.replies[0].text, "asking for a number we already have looks careless"


def test_intake_messages_pass_through_to_the_ai_pipeline(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "intake"})

    out = _handle(_db(), "Nithya, nithya@gmail.com, 600073")

    assert out.stop is False
    assert out.replies == []
    assert out.text == "Nithya, nithya@gmail.com, 600073"


def test_the_carried_over_first_message_is_merged_into_the_intake(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps(
        {"state": "intake", "carryOver": "Power cut in Madambakkam"})

    out = _handle(_db(), "Nithya, 600073")

    assert "Power cut in Madambakkam" in out.text
    assert "Nithya" in out.text
    # Consumed exactly once.
    assert "carryOver" not in json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])


def test_registration_closes_the_conversation_with_the_ticket_details(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "intake"})
    db = _db(ticket=_ticket(status="open", eta_at=None))

    replies = _run(menu.finish_registration(db, TENANT, THREAD, "t-1", "TKT-00042", {}))

    assert "TKT-00042" in replies[0].text
    assert "registered" in replies[0].text.lower()
    assert "main menu will open again" in replies[1].text
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store


def test_registration_close_out_is_skipped_when_the_thread_was_not_in_intake(fake_valkey):
    """A ticket filed some other way must still get the ordinary acknowledgement."""
    assert _run(menu.finish_registration(_db(), TENANT, THREAD, "t-1", "TKT-00042", {})) is None


# --- the # shortcut and mis-keys -------------------------------------------

def test_hash_returns_to_the_main_menu_from_every_state(fake_valkey):
    for state in ("menu", "await_ticket_id", "await_note", "intake"):
        fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": state})

        out = _handle(_db(), "#")

        assert _is_main_menu(out.replies[0]), f"# must work from {state}"
        assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


def test_hash_mid_conversation_does_not_greet_again(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "intake"})

    out = _handle(_db(), "#")

    assert "Welcome" not in out.replies[0].text


def test_an_unrecognised_menu_key_re_shows_the_options(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "9")

    assert "didn't catch that" in out.replies[0].text
    assert _is_main_menu(out.replies[0]), "the options must come back with the apology"


def test_option_keys_tolerate_how_people_actually_type(fake_valkey):
    for typed in ("1", "1.", "1)", " 1 ", "one", "Status"):
        fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
        out = _handle(_db(), typed)
        assert "Ticket ID" in out.replies[0].text, f"{typed!r} should select option 1"


def test_a_button_reply_title_selects_its_option(fake_valkey):
    """WhatsApp interactive buttons arrive as the button's TITLE, not its
    number — see WhatsAppParser. Without this the buttons would be dead."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "Register a new ticket")

    assert "register a new ticket" in out.replies[0].text.lower()


# --- configuration ---------------------------------------------------------

def test_a_disabled_menu_passes_everything_through_untouched(fake_valkey):
    out = _handle(_db(), "power cut", {"whatsappMenu": {"enabled": False}})

    assert out.stop is False
    assert out.replies == []
    assert not fake_valkey.store


def test_tenant_copy_overrides_the_defaults(fake_valkey):
    out = _handle(_db(), "hi", {"whatsappMenu": {
        "welcome": "Vanakkam! {company} here.", "companyName": "TNEB"}})

    assert "Vanakkam! TNEB here." in out.replies[0].text


def test_a_blank_configured_string_falls_back_to_the_default(fake_valkey):
    """Blank means "use the default" — a blank welcome would otherwise send
    the citizen an empty WhatsApp message."""
    out = _handle(_db(), "hi", {"whatsappMenu": {"welcome": "   "}})

    assert "Welcome to" in out.replies[0].text


def test_a_template_with_a_stray_brace_does_not_break_the_reply(fake_valkey):
    """The templates are admin-editable. A typo must not turn into a citizen
    receiving no reply at all — which is what str.format would do here."""
    out = _handle(_db(), "hi", {"whatsappMenu": {"welcome": "Hello from {company} {oops"}})

    assert "Hello from UniServe {oops" in out.replies[0].text


def test_the_session_ttl_is_applied_and_capped(fake_valkey):
    _handle(_db(), "hi", {"whatsappMenu": {"sessionTtlHours": 6}})
    assert fake_valkey.ttls[f"wamenu:{TENANT}:{THREAD}"] == 6 * 3600

    _handle(_db(), "hi", {"whatsappMenu": {"sessionTtlHours": 999}}, thread="whatsapp:+91999")
    assert fake_valkey.ttls["wamenu:t1:whatsapp:+91999"] == \
        menu_content.DEFAULT_SESSION_TTL_HOURS * 3600


def test_an_unknown_stored_state_restarts_rather_than_guessing(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "who_knows"})

    out = _handle(_db(), "hello")

    assert _is_main_menu(out.replies[0])


def test_a_valkey_outage_degrades_to_the_welcome_menu_not_a_wrong_flow(fake_valkey):
    """An unreadable session must not be treated as some assumed state — that
    would file the citizen's next message against a flow they are not in."""
    with patch.object(type(fake_valkey), "get", AsyncMock(side_effect=RuntimeError("down"))):
        out = _handle(_db(), "TKT-00042")

    assert _is_main_menu(out.replies[0])


# --- Feature 28: a citizen ANSWERING us is not a citizen INITIATING a chat ---
#
# The reported bug: an agent sends a follow-up from the ticket screen, the
# citizen replies on WhatsApp, and the reply got the welcome menu instead of
# landing on the ticket — so the agent never saw the answer.

def _awaiting_db(last_message, ticket_id="t-1"):
    db = _db()
    db.list_tickets = AsyncMock(return_value=[{"id": ticket_id, "ticket_number": "TKT-00042"}])
    db.find_by_phone = AsyncMock(return_value={"master_id": "master-1"})
    db.get_messages = AsyncMock(return_value=[last_message] if last_message else [])
    db.find_message_by_channel_id = AsyncMock(return_value=None)
    return db


def _outbound(created_at="2999-01-01 00:00:00", **extra):
    msg = {"direction": "outbound", "content": "Which street is this on?",
           "created_at": created_at}
    msg.update(extra)
    return msg


def test_a_reply_to_an_agents_follow_up_skips_the_menu(fake_valkey):
    db = _awaiting_db(_outbound())

    out = _run(menu.handle_inbound(db, TENANT, THREAD, "It's on 2nd Street",
                                   identity_value=PHONE, tenant_config={}))

    assert out.stop is False, "the answer must reach the routing ladder, not the menu"
    assert out.replies == []
    assert out.text == "It's on 2nd Street"
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store


def test_a_swipe_reply_to_one_of_our_messages_skips_the_menu(fake_valkey):
    """The exact, interpretation-free signal: Meta hands us the wamid of the
    message they replied to."""
    db = _awaiting_db(None)
    db.find_message_by_channel_id = AsyncMock(return_value={"id": "m-9", "ticket_id": "t-1"})

    out = _run(menu.handle_inbound(db, TENANT, THREAD, "Yes it is", identity_value=PHONE,
                                   tenant_config={}, in_reply_to="wamid.OURS"))

    assert out.stop is False
    assert out.text == "Yes it is"


def test_a_genuine_first_contact_still_gets_the_menu(fake_valkey):
    """The citizen owns no tickets, so nothing is awaiting their reply."""
    db = _awaiting_db(None)
    db.list_tickets = AsyncMock(return_value=[])

    out = _handle(db, "hi")

    assert out.stop is True
    assert _is_main_menu(out.replies[0])
    # And it cost one indexed query, with no message fetches.
    db.get_messages.assert_not_awaited()


def test_a_ticket_where_the_citizen_spoke_last_does_not_suppress_the_menu(fake_valkey):
    """We are not waiting on them — they are waiting on us. A new message from
    them is a new conversation, and the menu is how it starts."""
    db = _awaiting_db({"direction": "inbound", "content": "any update?",
                       "created_at": "2999-01-01 00:00:00"})

    out = _handle(db, "hello")

    assert out.stop is True
    assert _is_main_menu(out.replies[0])


def test_a_stale_outbound_message_does_not_suppress_the_menu(fake_valkey):
    """Outside the reply window the exchange is over; a message weeks later is
    a fresh conversation."""
    db = _awaiting_db(_outbound(created_at="2000-01-01 00:00:00"))

    out = _handle(db, "hello")

    assert out.stop is True
    assert _is_main_menu(out.replies[0])


def test_an_unanswered_intake_question_does_not_suppress_the_menu(fake_valkey):
    """An intake request belongs to option 2's own flow, which carries its own
    session. Reaching here means that session is gone, so the form is over."""
    db = _awaiting_db(_outbound(is_intake_request=1))

    out = _handle(db, "Nithya")

    assert out.stop is True
    assert _is_main_menu(out.replies[0])


def test_an_active_menu_session_still_wins_over_the_awaiting_check(fake_valkey):
    """Mid-flow the session is authoritative — a citizen who pressed 1 and is
    typing a ticket number must not be diverted because a ticket also happens
    to be awaiting them."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _awaiting_db(_outbound())
    db.get_ticket = AsyncMock(return_value=_ticket())
    db.list_tickets = AsyncMock(return_value=[_ticket()])

    out = _handle(db, "TKT-00042")

    assert out.stop is True
    assert "TKT-00042" in out.replies[0].text


def test_the_hash_escape_still_wins_over_the_awaiting_check(fake_valkey):
    db = _awaiting_db(_outbound())

    out = _handle(db, "#")

    assert out.stop is True
    assert _is_main_menu(out.replies[0])


def test_a_lookup_failure_falls_back_to_the_menu_rather_than_erroring(fake_valkey):
    db = _awaiting_db(_outbound())
    db.list_tickets = AsyncMock(side_effect=RuntimeError("db down"))

    out = _handle(db, "hello")

    assert out.stop is True
    assert _is_main_menu(out.replies[0])


# --- the chief complaint in the reply --------------------------------------

def test_the_reply_names_what_the_complaint_was_about(fake_valkey):
    """A status alone means nothing to a citizen holding three open tickets."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(chief_complaint="Power cut in Madambakkam since yesterday"),
             identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert "Power cut in Madambakkam since yesterday" in out.replies[0].text


def test_a_ticket_with_no_chief_complaint_says_so_rather_than_a_bare_label(fake_valkey):
    """A stub still mid-intake, or a ticket predating Feature 23, has none —
    and "Complaint:" with nothing after it reads as a bug."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(chief_complaint=None), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert "not summarised yet" in out.replies[0].text
    assert "Complaint:\n" not in out.replies[0].text


def test_the_registration_confirmation_also_names_the_complaint(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "intake"})
    db = _db(ticket=_ticket(status="open", eta_at=None,
                            chief_complaint="No water supply in Velachery"))

    replies = _run(menu.finish_registration(db, TENANT, THREAD, "t-1", "TKT-00042", {}))

    assert "No water supply in Velachery" in replies[0].text


def test_an_answer_reaches_the_ticket_even_with_a_live_menu_session(fake_valkey):
    """The reported bug, exactly.

    The citizen used the menu earlier, so a session is still alive (12h TTL).
    An agent then replies "Is this resolved?" from the ticket screen and the
    citizen answers. The answer matches no menu option, and the first version
    of this fix only checked the NO-session branch — so they were told "Sorry,
    I didn't catch that" and their answer never reached the ticket.
    """
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
    db = _awaiting_db(_outbound(content="Is this resolved?"))

    out = _handle(db, "Yes it is resolved now")

    assert out.stop is False, "the answer must reach the routing ladder"
    assert out.replies == []
    assert out.text == "Yes it is resolved now"
    # The agent has taken the conversation over; a stale menu state would send
    # the citizen's NEXT message somewhere wrong too.
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store


def test_a_swipe_reply_reaches_the_ticket_even_with_a_live_menu_session(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
    db = _awaiting_db(None)
    db.find_message_by_channel_id = AsyncMock(return_value={"id": "m-9", "ticket_id": "t-1"})

    out = _run(menu.handle_inbound(db, TENANT, THREAD, "Yes", identity_value=PHONE,
                                   tenant_config={}, in_reply_to="wamid.OURS"))

    assert out.stop is False
    assert out.text == "Yes"


def test_choosing_an_option_still_wins_over_an_awaiting_ticket(fake_valkey):
    """A citizen who deliberately taps "Ticket status" must get the menu flow,
    even when a ticket also happens to be waiting on them."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
    db = _awaiting_db(_outbound())

    out = _handle(db, "Ticket status")

    assert out.stop is True
    assert "Ticket ID" in out.replies[0].text


def test_a_mis_key_with_nothing_awaiting_still_re_shows_the_menu(fake_valkey):
    """The fix must not swallow genuine mis-keys into the routing ladder."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
    db = _awaiting_db({"direction": "inbound", "content": "hi",
                       "created_at": "2999-01-01 00:00:00"})

    out = _handle(db, "9")

    assert out.stop is True
    assert "didn't catch that" in out.replies[0].text
