"""REZO-specific persistence migration coverage."""

from rezo_persistence_support import make_record, run_boot
from top.rezo.rezo_persistence import RezoStateJournal


def test_version_one_record_loads_with_current_tail_defaults():
    slot = 4
    base = RezoStateJournal.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * RezoStateJournal.SLOT_BYTES)
    old_words = [0x1234, 0x5678, 0x9abc, 0xdef0]
    tail = (0x1357, 0x2468)
    record = make_record(
        RezoStateJournal, old_words, generation=5,
        version=RezoStateJournal.LEGACY_VERSION)
    contents = {base + n: byte for n, byte in enumerate(record)}
    run_boot(
        RezoStateJournal, contents, old_words + list(tail), slot=slot,
        state_words=6,
        journal_kwargs={"legacy_state_words": 4,
                        "legacy_tail_words": tail})
