"""Reviewed help must match the firmware and fit the bounded view/storage."""
from top.intono import help_content


def test_help_source_matches_generated_firmware():
    expected = help_content.render()
    assert (help_content.ROOT / 'fw/src/help_text.rs').read_text() == expected
    assert len(help_content.TOPICS) == 10
