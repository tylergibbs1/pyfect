"""Event sourcing with sync (Effect's ``effect/eventlog``).

``event`` and ``event_group`` declare events; ``event_log`` writes them to
an ``event_journal`` and replays them through handlers; ``event_row``
makes events that keep table rows. ``event_log_remote`` syncs a log with
a server (``event_log_server_encrypted`` stores batches it cannot read,
``event_log_server_unencrypted`` runs the handlers itself), over the RPCs
of ``event_log_message``, encrypted by ``event_log_encryption`` (the
``eventlog`` extra, ``cryptography``) and authenticated by
``event_log_session_auth``. ``sql_event_journal``,
``sql_event_log_server_encrypted`` and ``sql_event_log_server_unencrypted``
keep the journal and the server storages in a SQLite or PostgreSQL
database.

Import it as a submodule (``from pyfect import eventlog``): ``import pyfect``
does not load it, since its servers load ``pyfect.rpc``.

Payloads and messages are their schemas' JSON as UTF-8 bytes: Effect's
``SchemaBinary`` (MessagePack) is not ported, so pyfect peers cannot talk
to Effect ones.
"""

from pyfect.eventlog import (
    event,
    event_group,
    event_journal,
    event_log,
    event_log_encryption,
    event_log_message,
    event_log_remote,
    event_log_server,
    event_log_server_encrypted,
    event_log_server_unencrypted,
    event_log_session_auth,
    event_row,
    sql_event_journal,
    sql_event_log_server_encrypted,
    sql_event_log_server_unencrypted,
)
from pyfect.eventlog.event import Event, Write
from pyfect.eventlog.event_group import EventGroup
from pyfect.eventlog.event_journal import Entry, EventJournal, EventJournalError, RemoteEntry
from pyfect.eventlog.event_log import EventLog, Identity, Registry
from pyfect.eventlog.event_log_encryption import EventLogEncryption
from pyfect.eventlog.event_log_remote import EventLogRemote, EventLogRemoteError
from pyfect.eventlog.event_row import EventRow

__all__ = [
    "Entry",
    "Event",
    "EventGroup",
    "EventJournal",
    "EventJournalError",
    "EventLog",
    "EventLogEncryption",
    "EventLogRemote",
    "EventLogRemoteError",
    "EventRow",
    "Identity",
    "Registry",
    "RemoteEntry",
    "Write",
    "event",
    "event_group",
    "event_journal",
    "event_log",
    "event_log_encryption",
    "event_log_message",
    "event_log_remote",
    "event_log_server",
    "event_log_server_encrypted",
    "event_log_server_unencrypted",
    "event_log_session_auth",
    "event_row",
    "sql_event_journal",
    "sql_event_log_server_encrypted",
    "sql_event_log_server_unencrypted",
]
