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
    """The menu is the menu whether it arrives as options or as "Press 1"."""
    if message.buttons:
        return len(message.buttons) == 4
    return all(x in message.text for x in ("Press 1", "Press 2", "Press 3", "Press 4"))


def _hint(message):
    """The "press #" line, wherever it ended up — footer with options, body without."""
    return (message.text or "") + "\n" + (message.footer or "")


def _button_titles(message):
    return [b["title"] for b in (message.buttons or [])]


# --- first contact ---------------------------------------------------------

def test_the_ai_speaks_first_with_the_company_name_and_the_four_options(fake_valkey):
    out = _handle(_db(), "hi", {"landingPage": {"brandName": "TNEB"}})

    assert out.stop is True
    message = out.replies[0]
    assert "Welcome to TNEB" in message.text
    # Feature 28 made the options tappable; Feature 29 added a fourth, which
    # is why they go out as a list — Meta caps reply-buttons at three.
    assert _button_titles(message) == [
        "Update my details", "Ticket status", "New ticket", "End chat"]
    assert [b["id"] for b in message.buttons] == [
        "menu_profile", "menu_status", "menu_new", "menu_end"]
    assert message.list_label == "Choose an option"
    # The # escape moves to the footer, where WhatsApp renders it under the buttons.
    assert "#" in (message.footer or "")
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


def test_the_options_fall_back_to_numbered_text_when_buttons_are_off(fake_valkey):
    """A tenant can opt out, and then the body must carry the options itself."""
    out = _handle(_db(), "hi", {"whatsappMenu": {"useInteractiveButtons": False}})

    message = out.replies[0]
    assert message.buttons is None
    assert all(x in message.text for x in ("Press 1", "Press 2", "Press 3", "Press 4"))
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

def test_the_end_chat_option_says_goodbye_and_ends_the_session(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "4")

    assert [m.text for m in out.replies] == ["Thanks for reaching out. Have a great time"]
    assert f"wamenu:{TENANT}:{THREAD}" not in fake_valkey.store
    # No "press # for the menu" here: the conversation is over, and offering a
    # way back into a menu we just closed contradicts the goodbye.
    assert "#" not in out.replies[0].text


def test_a_message_after_the_chat_ended_re_opens_the_main_menu(fake_valkey):
    out = _handle(_db(), "hello again")
    assert _is_main_menu(out.replies[0])


# --- option 1: status, ETA, last updated -----------------------------------

def test_the_status_option_says_so_when_they_have_no_tickets(fake_valkey):
    """`_db()` knows no identity for this number, so there is nothing to list."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "2")

    assert "don't have any" in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


def test_a_ticket_id_returns_that_one_ticket_with_status_eta_and_last_updated(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_ticket_id"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042")

    text = out.replies[0].text
    assert "TKT-00042" in text
    assert "Work in progress" in text
    assert "18 Aug 2026" in text      # the ETA
    assert "15 Aug 2026" in text      # last updated
    assert "#" in _hint(out.replies[0])


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
    # Back AT the menu rather than cleared (Feature 29): the acknowledgement
    # carries a Main menu option, and tapping it must open the menu rather
    # than read as a brand-new conversation.
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


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

def test_the_new_ticket_option_lists_the_details_needed_and_hands_off(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "3")

    assert "register a new ticket" in out.replies[0].text.lower()
    # The tenant's configured intake form, not a hardcoded list.
    assert "1." in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "intake"


def test_the_new_ticket_option_does_not_ask_for_the_number_we_already_have(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "3")

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


def test_registration_confirms_in_exactly_one_message_with_a_way_back(fake_valkey):
    """Feature 29. Two messages back to back — the details, then "we're ending
    this conversation here" — read as a system talking to itself, right after
    the citizen did the one thing that most deserves a clean confirmation."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "intake"})
    db = _db(ticket=_ticket(status="open", eta_at=None))

    replies = _run(menu.finish_registration(db, TENANT, THREAD, "t-1", "TKT-00042", {}))

    assert len(replies) == 1
    assert "TKT-00042" in replies[0].text
    assert "registered" in replies[0].text.lower()
    assert [b["title"] for b in replies[0].buttons] == ["Main menu"]
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


def test_registration_close_out_is_skipped_when_the_thread_was_not_in_intake(fake_valkey):
    """A ticket filed some other way must still get the ordinary acknowledgement."""
    assert _run(menu.finish_registration(_db(), TENANT, THREAD, "t-1", "TKT-00042", {})) is None


# --- the # shortcut and mis-keys -------------------------------------------

def test_hash_returns_to_the_main_menu_from_every_state(fake_valkey):
    for state in ("menu", "profile", "await_name", "await_email",
                  "await_ticket_choice", "await_ticket_id", "await_note", "intake"):
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
    for typed in ("2", "2.", "2)", " 2 ", "two", "Status"):
        fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
        out = _handle(_db(), typed)
        assert "don't have any" in out.replies[0].text, f"{typed!r} selects ticket status"


def test_a_button_reply_title_selects_its_option(fake_valkey):
    """WhatsApp interactive buttons arrive as the button's TITLE, not its
    number — see WhatsAppParser. Without this the buttons would be dead."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "New ticket")

    assert "register a new ticket" in out.replies[0].text.lower()


def test_a_complaint_that_merely_starts_with_an_alias_is_not_a_menu_key(fake_valkey):
    """`_match_option` used to try the first word too, so "new water logging
    problem in my street" was read as option 2 and the complaint was lost."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "New water logging problem in my street")

    assert "didn't catch that" in out.replies[0].text
    session = json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])
    assert session["carryOver"] == "New water logging problem in my street"


def test_a_chosen_option_is_never_read_as_an_answer_to_an_agent(fake_valkey):
    """The live failure: an agent had an unanswered "Is this resolved?" open, so
    the awaiting-reply check said yes to EVERYTHING — the citizen's "3", then
    their "New ticket" tap, then the complaint they typed all bypassed the menu
    and were filed onto the old ticket. They could not get out."""
    db = _awaiting_db(_outbound(content="Is this resolved?"))

    # At the menu, an option is acted on and the awaiting check is not consulted.
    for typed, expected in [("4", "Thanks for reaching out"),
                            ("New ticket", "register a new ticket"),
                            ("Ticket status", "Here are your tickets")]:
        fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
        db.get_messages.reset_mock()

        out = _handle(db, typed)

        assert out.stop is True, f"{typed!r} must be handled by the menu"
        assert expected.lower() in out.replies[0].text.lower(), typed
        db.get_messages.assert_not_awaited()

    # And with no session at all an option still reaches the MENU, never the
    # ticket — this is the branch that was swallowing "3" into TKT-00014.
    for typed in ("4", "New ticket", "Ticket status"):
        await_clear = fake_valkey.store.pop(f"wamenu:{TENANT}:{THREAD}", None)
        db.get_messages.reset_mock()

        out = _handle(db, typed)

        assert out.stop is True, f"{typed!r} must never reach the routing ladder"
        db.get_messages.assert_not_awaited()


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


def _outbound(created_at="2999-01-01 00:00:00", author_type="agent", **extra):
    msg = {"direction": "outbound", "content": "Which street is this on?",
           "author_type": author_type, "created_at": created_at}
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
    assert "Here are your tickets" in out.replies[0].text


def test_a_mis_key_with_nothing_awaiting_still_re_shows_the_menu(fake_valkey):
    """The fix must not swallow genuine mis-keys into the routing ladder."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
    db = _awaiting_db({"direction": "inbound", "content": "hi",
                       "created_at": "2999-01-01 00:00:00"})

    out = _handle(db, "9")

    assert out.stop is True
    assert "didn't catch that" in out.replies[0].text


def test_our_own_ai_reply_does_not_keep_the_citizen_trapped(fake_valkey):
    """The reported trap.

    The citizen answers an agent, the assistant replies — and because that
    reply is also an outbound message, every LATER message was still counted as
    "an answer". So "Hi" bypassed the menu, fell through the routing ladder to
    "we couldn't tell which complaint this is about", and the second "Hi" got
    silence (the ask had already escalated). Only `#` got them out.

    An agent asking a question is a state we are waiting on. Us having spoken
    is not.
    """
    db = _awaiting_db(_outbound(author_type="ai",
                                content="Thank you for your response!"))

    out = _handle(db, "Hi")

    assert out.stop is True, "the menu must take this, not the routing ladder"
    assert _is_main_menu(out.replies[0])


def test_a_system_notification_does_not_count_as_awaiting_either(fake_valkey):
    """Status-update notifications are outbound but ask nothing."""
    db = _awaiting_db(_outbound(author_type="system",
                                content="Your ticket has been resolved."))

    out = _handle(db, "ok thanks")

    assert out.stop is True
    assert _is_main_menu(out.replies[0])


def test_an_agents_question_still_counts(fake_valkey):
    """The case the whole check exists for must keep working."""
    db = _awaiting_db(_outbound(author_type="agent", content="Is this resolved?"))

    out = _handle(db, "Yes it is")

    assert out.stop is False
    assert out.text == "Yes it is"


# ---------------------------------------------------------------------------
# Feature 29: a structured, standardised conversation
# ---------------------------------------------------------------------------
#
# Four options instead of three, the citizen greeted by name, their tickets
# listed rather than asked for by number, and a way back to the main menu on
# every message below the top level.


def _known_db(name="Ashok", **overrides):
    """A number we already recognise."""
    identity = {"id": "i-1", "master_id": "master-1", "name": name}
    identity.update(overrides)
    db = _db(identity=identity)
    db.update_identity = AsyncMock(return_value={"id": "i-1"})
    db.create_identity = AsyncMock(return_value={"id": "i-2"})
    return db


def _rejected(status):
    """An httpx-shaped failure, which is all the menu inspects."""
    error = RuntimeError("rejected")
    error.response = MagicMock()
    error.response.status_code = status
    return error


def _titles(message):
    return [b["title"] for b in (message.buttons or [])]


# --- greeting by name ------------------------------------------------------

def test_a_number_we_recognise_is_greeted_by_name(fake_valkey):
    """The first thing Feature 29 asks for: identify the number, then greet."""
    out = _handle(_known_db("Ashok"), "hi", {"landingPage": {"brandName": "TNEB"}})

    assert "Hello Ashok" in out.replies[0].text
    assert "TNEB" in out.replies[0].text


def test_a_number_we_do_not_know_still_gets_a_welcome(fake_valkey):
    """No name is not an error — and the profile option doubles as onboarding."""
    out = _handle(_db(), "hi")

    assert "Welcome to" in out.replies[0].text
    assert "Update my details" in _titles(out.replies[0])


def test_an_identity_lookup_failure_costs_the_name_not_the_greeting(fake_valkey):
    db = _db()
    db.find_by_phone = AsyncMock(side_effect=RuntimeError("db down"))

    out = _handle(db, "hi")

    assert _is_main_menu(out.replies[0])


# --- the way back ----------------------------------------------------------

def test_every_sub_message_carries_a_main_menu_option(fake_valkey):
    """"Press #" was always true and always invisible: the citizen is looking
    at buttons."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_db(), "3")   # new ticket

    assert "Main menu" in _titles(out.replies[0])


def test_tapping_main_menu_returns_to_the_menu_from_any_state(fake_valkey):
    for state in ("profile", "await_name", "await_email", "await_ticket_choice",
                  "await_ticket_id", "await_note", "intake"):
        fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": state})

        out = _handle(_db(), "Main menu")

        assert _is_main_menu(out.replies[0]), f"Main menu must work from {state}"
        assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


# --- option 1: update my details -------------------------------------------

def test_the_profile_option_offers_name_email_and_a_way_back(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_known_db(), "1")

    assert _titles(out.replies[0]) == ["Name", "Email", "Main menu"]
    # Three options fit reply-buttons, so this one is NOT a list.
    assert len(out.replies[0].buttons) <= 3
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "profile"


def test_choosing_name_asks_for_it_and_their_reply_is_the_submit(fake_valkey):
    """WhatsApp has no text box with a Submit button outside a published Flow,
    so we ask, they reply, and the Main menu option on the ask is the cancel."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "profile"})
    db = _known_db()

    out = _handle(db, "Name")

    assert "type your full name" in out.replies[0].text
    assert "Main menu" in _titles(out.replies[0])
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_name"


def test_a_citizen_we_have_no_name_for_is_onboarded_rather_than_corrected(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "profile"})

    out = _handle(_db(), "Name")

    assert "don't have your name yet" in out.replies[0].text


def test_a_typed_name_is_saved_as_a_correction_not_an_enrichment(fake_valkey):
    """db-writer's PATCH refuses to touch a field it already holds — which is
    exactly the value the citizen is trying to fix."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_name"})
    db = _known_db("Ashok")

    out = _handle(db, "Ashok Srinivasan")

    identity_id, payload = db.update_identity.await_args.args
    assert identity_id == "i-1"
    assert payload == {"name": "Ashok Srinivasan", "overwrite": True}
    assert "Ashok Srinivasan" in out.replies[0].text
    assert "Main menu" in _titles(out.replies[0])
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "menu"


def test_a_number_with_no_identity_gets_one_created(fake_valkey):
    """The profile option doubles as onboarding for someone who has never
    filed anything."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_name"})
    db = _db()
    db.create_identity = AsyncMock(return_value={"id": "i-9"})

    _handle(db, "Nithya")

    assert db.create_identity.await_args.args[0] == {
        "tenantId": TENANT, "phone": PHONE, "name": "Nithya"}


def test_a_name_that_is_not_a_name_is_re_asked_without_losing_the_flow(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_name"})
    db = _known_db()

    out = _handle(db, "12345")

    assert "doesn't look like a name" in out.replies[0].text
    db.update_identity.assert_not_awaited()
    # Still mid-correction: dropping them at the menu would make them start over.
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_name"


def test_a_typed_email_is_saved_and_confirmed(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_email"})
    db = _known_db()

    out = _handle(db, "ashok@example.com")

    assert db.update_identity.await_args.args[1] == {
        "email": "ashok@example.com", "overwrite": True}
    assert "ashok@example.com" in out.replies[0].text


def test_an_address_that_is_not_an_email_is_rejected_before_the_write(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_email"})
    db = _known_db()

    out = _handle(db, "ashok at example")

    assert "doesn't look like an email" in out.replies[0].text
    db.update_identity.assert_not_awaited()


def test_an_email_another_identity_holds_is_refused_and_explained(fake_valkey):
    """Taking an address that identifies someone else is not an edit — it is a
    silent reassignment of whoever owns those tickets. db-writer 409s it."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "await_email"})
    db = _known_db()
    db.update_identity = AsyncMock(side_effect=_rejected(409))

    out = _handle(db, "priya@example.com")

    assert "already registered" in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_email"


# --- option 2: their tickets, listed ---------------------------------------

def _listing_db(count, status="in_progress"):
    tickets = [{"id": f"t-{i}", "ticket_number": f"TKT-{i:05d}", "status": status,
                "chief_complaint": f"Power cut in area {i}",
                "updated_at": "2026-08-15 04:00:00", "identity_id": "master-1"}
               for i in range(1, count + 1)]
    db = _db(tickets=tickets, identity={"id": "i-1", "master_id": "master-1", "name": "Ashok"})
    return db


def test_five_or_fewer_tickets_are_all_listed_with_a_way_back(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_listing_db(3), "2")

    message = out.replies[0]
    assert "Here are your tickets" in message.text
    assert _titles(message)[-1] == "Main menu"
    assert len(message.buttons) == 4          # three tickets + the way back
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == \
        "await_ticket_choice"


def test_a_ticket_row_names_the_complaint_within_metas_caps(fake_valkey):
    """The 72-character description is what finally gives the complaint room —
    a reply-button has no second line at all."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    row = _handle(_listing_db(1), "2").replies[0].buttons[0]

    assert row["title"].startswith("TKT-00001")
    assert len(row["title"]) <= menu.ROW_TITLE_MAX
    assert "Work in progress" in row["description"]
    assert len(row["description"]) <= menu.ROW_DESCRIPTION_MAX


def test_the_list_asks_only_for_open_and_resolved_tickets(fake_valkey):
    """Closed is excluded because a finished ticket is not what they are
    chasing; cancelled because nobody is waiting on it."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
    db = _listing_db(2)

    _handle(db, "2")

    statuses = db.list_tickets.await_args.kwargs["status"].split(",")
    assert "resolved" in statuses
    assert "closed" not in statuses and "cancelled" not in statuses


def test_more_than_five_tickets_asks_for_the_number_but_still_offers_a_list(fake_valkey):
    """Meta's list holds ten rows, and two of them are navigation."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_listing_db(9), "2")

    assert "9 tickets" in out.replies[0].text
    assert len(out.replies[0].buttons) == menu.LIST_ROWS_MAX
    assert _titles(out.replies[0])[-2:] == ["Not listed — type ID", "Main menu"]


def test_tapping_a_ticket_row_returns_that_ticket(fake_valkey):
    """A tap arrives as the row's TITLE, which starts with the ticket number."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps(
        {"state": "await_ticket_choice"})
    db = _db(ticket=_ticket(), identity={"master_id": "master-1"})

    out = _handle(db, "TKT-00042 Power cut in")

    assert "TKT-00042" in out.replies[0].text
    assert "Work in progress" in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == "await_note"


def test_the_not_listed_row_asks_for_the_ticket_id(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps(
        {"state": "await_ticket_choice"})

    out = _handle(_db(), "Not listed — type ID")

    assert "Ticket ID" in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == \
        "await_ticket_id"


def test_a_listing_failure_falls_back_to_asking_for_the_number(fake_valkey):
    """The Feature 26 exchange only ever needed the number, so there is
    somewhere sane to fall back to."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
    db = _listing_db(2)
    db.list_tickets = AsyncMock(side_effect=RuntimeError("db down"))

    out = _handle(db, "2")

    assert "Ticket ID" in out.replies[0].text
    assert json.loads(fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"])["state"] == \
        "await_ticket_id"


def test_a_tenant_with_interactive_messages_off_is_asked_for_the_number(fake_valkey):
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})

    out = _handle(_listing_db(3), "2", {"whatsappMenu": {"useInteractiveButtons": False}})

    assert "Ticket ID" in out.replies[0].text
    assert out.replies[0].buttons is None


# --- the free-text rule, scoped ---------------------------------------------

def test_free_text_at_the_menu_greets_and_re_shows_the_options(fake_valkey):
    """The user's rule, at the level it belongs: nothing is awaiting them and
    they are at the top of the conversation."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps({"state": "menu"})
    db = _known_db("Ashok")
    db.list_tickets = AsyncMock(return_value=[])

    out = _handle(db, "are you there?")

    assert "Hello Ashok" in out.replies[0].text
    assert "didn't catch that" in out.replies[0].text
    assert _is_main_menu(out.replies[0])


def test_free_text_inside_a_flow_is_that_flows_input_not_a_menu_return(fake_valkey):
    """Applied literally, "any message outside the options returns to the main
    menu" would undo every Feature 28 follow-up and make the flows unusable —
    a note, a name and a complaint are all "outside the options"."""
    fake_valkey.store[f"wamenu:{TENANT}:{THREAD}"] = json.dumps(
        {"state": "await_note", "ticketId": "t-1", "ticketNumber": "TKT-00042"})
    db = _db(ticket=_ticket())

    out = _handle(db, "still no power after three days")

    assert db.add_message.await_args.args[1]["content"] == "still no power after three days"
    assert "team will revert" in out.replies[0].text
