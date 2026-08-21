"""REZOMO-specific persistence migration coverage."""

from rezo_persistence_support import make_record, run_boot
from top.rezo.persistence import RezoStateJournal


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


def test_version_three_loads_v2_and_v1_with_progressive_tail_defaults():
    slot = 4
    base = RezoStateJournal.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * RezoStateJournal.SLOT_BYTES)
    v1_words = [0x1111, 0x2222]
    v2_words = [0x3333, 0x4444, 0x5555, 0x6666]
    tail = (0xaaaa, 0xbbbb, 0xcccc, 0xdddd)
    journal_kwargs = {
        "legacy_records": (
            (RezoStateJournal.PREVIOUS_VERSION, 4),
            (RezoStateJournal.LEGACY_VERSION, 2),
        ),
        "legacy_tail_words": tail,
    }

    v2_record = make_record(
        RezoStateJournal, v2_words, generation=6,
        version=RezoStateJournal.PREVIOUS_VERSION)
    v2_contents = {base + n: byte for n, byte in enumerate(v2_record)}
    run_boot(
        RezoStateJournal, v2_contents, v2_words + list(tail[2:]), slot=slot,
        state_words=6, journal_kwargs=journal_kwargs)

    v1_record = make_record(
        RezoStateJournal, v1_words, generation=5,
        version=RezoStateJournal.LEGACY_VERSION)
    v1_contents = {base + n: byte for n, byte in enumerate(v1_record)}
    run_boot(
        RezoStateJournal, v1_contents, v1_words + list(tail), slot=slot,
        state_words=6, journal_kwargs=journal_kwargs)


def test_equal_length_v2_record_replaces_repurposed_words_with_defaults():
    slot = 4
    base = RezoStateJournal.OPTIONS_BASE_OFFSET + \
        ((slot + 1) * RezoStateJournal.SLOT_BYTES)
    v2_words = [0x1111, 0x2222, 0x3333, 0x4444]
    record = make_record(
        RezoStateJournal, v2_words, generation=7,
        version=RezoStateJournal.PREVIOUS_VERSION)
    contents = {base + n: byte for n, byte in enumerate(record)}
    run_boot(
        RezoStateJournal, contents,
        [0x1111, 0xaaaa, 0xbbbb, 0x4444], slot=slot, state_words=4,
        journal_kwargs={
            "legacy_records": ((RezoStateJournal.PREVIOUS_VERSION, 4),),
            "legacy_word_defaults": ((1, 0xaaaa), (2, 0xbbbb)),
        })
