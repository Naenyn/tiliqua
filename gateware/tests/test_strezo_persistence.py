"""STREZO-specific persistence migration coverage."""

from rezo_persistence_support import make_record, run_boot
from top.rezo.strezo_persistence import RezoStateJournal


def test_version_two_record_loads_with_current_tail_defaults():
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


def test_version_one_record_loads_through_both_migration_tails():
    slot = 5
    base = RezoStateJournal.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * RezoStateJournal.SLOT_BYTES)
    old_words = [0x1234, 0x5678]
    oldest_tail = (0x1111, 0x2222, 0x3333, 0x4444)
    record = make_record(
        RezoStateJournal, old_words, generation=6,
        version=RezoStateJournal.OLDEST_VERSION)
    contents = {base + n: byte for n, byte in enumerate(record)}
    run_boot(
        RezoStateJournal, contents, old_words + list(oldest_tail), slot=slot,
        state_words=6,
        journal_kwargs={
            "legacy_state_words": 4,
            "legacy_tail_words": (0x3333, 0x4444),
            "oldest_state_words": 2,
            "oldest_tail_words": oldest_tail,
        })
