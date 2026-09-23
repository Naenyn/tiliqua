import pytest
from nsdf_shared_history_probe import report, simulate


def test_shared_history_schedule():
    result=report()
    assert result['max_sample_age']<1024
    assert result['fir_latency_cycles']<=10000


def test_exact_filter_length_has_no_overwrite_guard():
    # A counterexample keeps the model honest: capacity equal to filter length
    # can overwrite a queued channel's oldest sample before its FIR job starts.
    with pytest.raises(AssertionError):simulate(0,depth=769)
