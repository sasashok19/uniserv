"""Strip the parts of an inbound message the citizen did not write (Feature 24).

An email reply normally carries our entire previous message quoted underneath
it, plus a signature. That is fine to STORE — an agent reading the thread may
want it — but it is actively harmful to every judgment routing makes about the
message:

- "Is this an answer to something we asked?" sees our own question inside the
  citizen's message and can answer yes to almost anything.
- "Does this read as a new complaint?" sees the original complaint quoted back
  and says yes, creating a duplicate ticket out of a one-word reply.
- The chief complaint would be derived from text we wrote ourselves.

So the raw body is what gets persisted, and the stripped body is what gets
assessed. Deliberately conservative: when the markers are ambiguous the whole
text is kept, because dropping a citizen's actual words is far worse than
leaving a quote in.
"""

import re

# Attribution lines mail clients put above a quote. Everything from here down is
# quoted material. Ordered loosest-last; all are anchored to a line start.
_QUOTE_HEADER_RE = re.compile(
    r"^\s*(?:"
    r">.*"                                          # a quoted line
    r"|On\s.{0,200}?\swrote:\s*"                    # Gmail/Apple: "On <date>, X wrote:"
    r"|-{2,}\s*Original Message\s*-{2,}"            # Outlook
    r"|_{5,}"                                       # Outlook's horizontal rule
    r"|From:\s.{0,200}"                             # Outlook header block
    r"|Sent from my \w+"                            # phone signatures
    r"|Get Outlook for \w+"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}.{0,80}wrote:\s*"
    r")\s*$",
    re.IGNORECASE)

# Our own outbound boilerplate coming back quoted — matched anywhere, not just
# at a line start, because a citizen may reply inline above or below it.
_OUR_BOILERPLATE_RE = re.compile(
    r"(?:If you have further questions, just reply to this (?:email|message)"
    r"|Your complaint has been updated"
    r"|Ticket ID:\s*TKT-\d{4,})",
    re.IGNORECASE)

_SIGNATURE_DELIM_RE = re.compile(r"^\s*--\s*$")


def strip_quoted_reply(text: str | None) -> str:
    """The part of `text` the citizen actually typed this time.

    Returns the original string when nothing identifiable can be removed, and
    never returns empty for a non-empty input: a message that is ENTIRELY quoted
    material is returned unchanged rather than blanked, so the caller still sees
    something to judge instead of silently treating it as an empty message.
    """
    original = (text or "").strip()
    if not original:
        return ""

    kept: list[str] = []
    for line in original.splitlines():
        if _QUOTE_HEADER_RE.match(line) or _SIGNATURE_DELIM_RE.match(line):
            break
        if _OUR_BOILERPLATE_RE.search(line):
            break
        kept.append(line)

    cleaned = "\n".join(kept).strip()
    # All of it looked like quoted material. Better to assess the raw text than
    # to hand the caller an empty string it would read as "no message".
    return cleaned or original
