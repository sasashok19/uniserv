"""UniServe ai-core identity resolver (Feature 03).

Resolves channel identities to a canonical identity profile: WhatsApp phones are
auto-confirmed, email triggers the identity gate (pending), and anonymous flows
mint an ANON-XXXX reference. Profiles are persisted via the db-writer API.
"""
