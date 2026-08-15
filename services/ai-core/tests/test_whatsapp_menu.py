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


# --- first contact ---------------------------------------------------------

def test_the_ai_speaks_first_with_the_company_name_and_the_three_options(fake_valkey):
    out = _handle(_db(), "hi", {"landingPage": {"brandName": "TNEB"}})

    assert out.stop is True
    text = out.replies[0]
    assert "Welcome to TNEB" in text
    assert "Press 1" in text and "Press 2" in text and "Press 3" in text
    assert "#" in text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


def test_the_company_name_is_configurable_independently_of_the_brand(fake_valkey):
    out = _handle(_db(), "hi", {"landingPage": {"brandName": "TNEB"},
                                "whatsappMenu": {"companyName": "TNEB Customer Care"}})
    assert "Welcome to TNEB Customer Care" in out.replies[0]


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

    assert out.replies == ["Thanks for reaching out. Have a great time"]
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store
    # No "press # for the menu" here: the conversation is over, and offering a
    # way back into a menu we just closed contradicts the goodbye.
    assert "#" not in out.replies[0]


def test_a_message_after_the_chat_ended_re_opens_the_main_menu(fake_valkey):
    out = _handle(_db(), "hello again")
    assert "Press 1" in out.replies[0]


# --- option 1: status, ETA, last updated -----------------------------------

def test_option_one_asks_for_the_ticket_id(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "1")

    assert "Ticket ID" in out.replies[0]
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_ticket_id"


def test_a_ticket_id_returns_that_one_ticket_with_status_eta_and_last_updated(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    text = out.replies[0]
    assert "TKT-00042" in text
    assert "Work in progress" in text
    assert "18 Aug 2026" in text      # the ETA
    assert "15 Aug 2026" in text      # last updated
    assert "#" in text


def test_only_that_one_ticket_is_reported_not_the_citizens_whole_list(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert "TKT-00043" not in out.replies[0]
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

    assert "couldn't find" in out.replies[0]
    assert "TKT-00042" not in out.replies[0].replace("TKT-00042)", "")
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_ticket_id"


def test_an_unknown_ticket_id_re_asks_rather_than_dropping_the_citizen(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(tickets=[])

    out = _handle(db, "TKT-99999")

    assert "couldn't find" in out.replies[0]
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_ticket_id"


def test_a_ticket_with_no_eta_says_so_rather_than_showing_a_blank(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(eta_at=None), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    assert "not set yet" in out.replies[0]


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

    assert "add" in out.replies[0].lower()
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

    assert "TKT-00042" in out.replies[0]
    assert "team will revert" in out.replies[0]
    assert "main menu will open again" in out.replies[1]
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store


def test_a_note_that_could_not_be_saved_is_never_acknowledged(fake_valkey):
    """Telling a citizen "the team will revert" about a note that does not
    exist is the one outcome here worse than an error message."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps(
        {"state": "await_note", "ticketId": "t-1", "ticketNumber": "TKT-00042"})
    db = _db(ticket=_ticket())
    db.add_message = AsyncMock(side_effect=RuntimeError("db down"))

    out = _handle(db, "still broken")

    assert "team will revert" not in out.replies[0]
    assert f"wamenu:{TENANT}:{THREAD}" in fake_valkey.store, "the citizen may retry"


# --- option 2 --------------------------------------------------------------

def test_option_two_lists_the_details_needed_and_hands_off_to_intake(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "2")

    assert "register a new ticket" in out.replies[0].lower()
    # The tenant's configured intake form, not a hardcoded list.
    assert "1." in out.replies[0]
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "intake"


def test_option_two_does_not_ask_for_the_phone_number_whatsapp_already_gave_us(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "2")

    assert "Mobile" not in out.replies[0], "asking for a number we already have looks careless"


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

    assert "TKT-00042" in replies[0]
    assert "registered" in replies[0].lower()
    assert "main menu will open again" in replies[1]
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store


def test_registration_close_out_is_skipped_when_the_thread_was_not_in_intake(fake_valkey):
    """A ticket filed some other way must still get the ordinary acknowledgement."""
    assert _run(menu.finish_registration(_db(), TENANT, THREAD, "t-1", "TKT-00042", {})) is None


# --- the # shortcut and mis-keys -------------------------------------------

def test_hash_returns_to_the_main_menu_from_every_state(fake_valkey):
    for state in ("menu", "await_ticket_id", "await_note", "intake"):
        fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": state})

        out = _handle(_db(), "#")

        assert "Press 1" in out.replies[0], f"# must work from {state}"
        assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


def test_hash_mid_conversation_does_not_greet_again(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "intake"})

    out = _handle(_db(), "#")

    assert "Welcome" not in out.replies[0]


def test_an_unrecognised_menu_key_re_shows_the_options(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "9")

    assert "didn't catch that" in out.replies[0]
    assert "Press 1" in out.replies[0]


def test_option_keys_tolerate_how_people_actually_type(fake_valkey):
    for typed in ("1", "1.", "1)", " 1 ", "one", "Status"):
        fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
        out = _handle(_db(), typed)
        assert "Ticket ID" in out.replies[0], f"{typed!r} should select option 1"


def test_a_button_reply_title_selects_its_option(fake_valkey):
    """WhatsApp interactive buttons arrive as the button's TITLE, not its
    number — see WhatsAppParser. Without this the buttons would be dead."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "Register a new ticket")

    assert "register a new ticket" in out.replies[0].lower()


# --- configuration ---------------------------------------------------------

def test_a_disabled_menu_passes_everything_through_untouched(fake_valkey):
    out = _handle(_db(), "power cut", {"whatsappMenu": {"enabled": False}})

    assert out.stop is False
    assert out.replies == []
    assert not fake_valkey.store


def test_tenant_copy_overrides_the_defaults(fake_valkey):
    out = _handle(_db(), "hi", {"whatsappMenu": {
        "welcome": "Vanakkam! {company} here.", "companyName": "TNEB"}})

    assert "Vanakkam! TNEB here." in out.replies[0]


def test_a_blank_configured_string_falls_back_to_the_default(fake_valkey):
    """Blank means "use the default" — a blank welcome would otherwise send
    the citizen an empty WhatsApp message."""
    out = _handle(_db(), "hi", {"whatsappMenu": {"welcome": "   "}})

    assert "Welcome to" in out.replies[0]


def test_a_template_with_a_stray_brace_does_not_break_the_reply(fake_valkey):
    """The templates are admin-editable. A typo must not turn into a citizen
    receiving no reply at all — which is what str.format would do here."""
    out = _handle(_db(), "hi", {"whatsappMenu": {"welcome": "Hello from {company} {oops"}})

    assert "Hello from UniServe {oops" in out.replies[0]


def test_the_session_ttl_is_applied_and_capped(fake_valkey):
    _handle(_db(), "hi", {"whatsappMenu": {"sessionTtlHours": 6}})
    assert fake_valkey.ttls[f"wamenu:{TENANT}:{THREAD}"] == 6 * 3600

    _handle(_db(), "hi", {"whatsappMenu": {"sessionTtlHours": 999}}, thread="whatsapp:+91999")
    assert fake_valkey.ttls["wamenu:t1:whatsapp:+91999"] == \
        menu_content.DEFAULT_SESSION_TTL_HOURS * 3600


def test_an_unknown_stored_state_restarts_rather_than_guessing(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "who_knows"})

    out = _handle(_db(), "hello")

    assert "Press 1" in out.replies[0]


def test_a_valkey_outage_degrades_to_the_welcome_menu_not_a_wrong_flow(fake_valkey):
    """An unreadable session must not be treated as some assumed state — that
    would file the citizen's next message against a flow they are not in."""
    with patch.object(type(fake_valkey), "get", AsyncMock(side_effect=RuntimeError("down"))):
        out = _handle(_db(), "TKT-00042")

    assert "Press 1" in out.replies[0]
