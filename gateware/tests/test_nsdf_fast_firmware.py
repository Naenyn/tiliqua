import os
from pathlib import Path
import shutil
import subprocess
import pytest
from analyze_nsdf_fast import analyze_fast


def test_physical_quiet_low_summaries_expose_slow_service():
    reports=list(analyze_fast((Path(__file__).parent/'fixtures/nsdf-fast-low-steady.txt').read_text()))
    assert len(reports)==3
    assert all(r['guarded_qualified'] and 24.3<r['hz']<24.5 for r in reports)
    assert all(350<r['frame_interval_ms']<390 for r in reports[1:])
    assert all(not r['score_parity_checked'] for r in reports)


@pytest.mark.parametrize('mode',['full','fast-native','fast-low','fast-all'])
def test_real_trace_state_machine_bounded_uart_and_cadence(tmp_path,mode):
    here=Path(__file__).parent;exe=tmp_path/'trace'
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    env=dict(os.environ,TILIQUA_TUNER_NSDF_TRACE=mode)
    subprocess.run([rustc,'--edition=2021','-O',str(here/'nsdf_trace_mock.rs'),'-o',str(exe)],env=env,check=True)
    output=subprocess.check_output([exe],text=True)
    if mode!='full':
        reports=list(analyze_fast(output,round_robin=mode=='fast-all'))
        assert len(reports)>100 and all(r['guarded_qualified'] for r in reports)
        # UART backpressure stretches cadence; never fabricate a fixed rate.
        assert max(r['frame_interval_ms'] or 0 for r in reports)>300
        assert all(not r['score_parity_checked'] for r in reports)
        if mode=='fast-all':
            assert {(r['channel'],r['bank']) for r in reports}=={
                (ch,bank) for ch in range(4) for bank in ('native','low')}
            # Reject skipped/duplicated banks, not merely eight report counts.
            blocks=output.split('NSDF SOURCE ')
            # An arbitrary first bank is allowed when connecting mid-cycle.
            assert list(analyze_fast('NSDF SOURCE '+blocks[2],round_robin=True))
            with pytest.raises(ValueError):
                list(analyze_fast('NSDF SOURCE '+blocks[1]+'NSDF SOURCE '+blocks[3],round_robin=True))


def test_physical_buffered_quiet_low_summaries_reach_20hz():
    reports=list(analyze_fast((Path(__file__).parent/'fixtures/nsdf-fast-low-buffered-steady.txt').read_text()))
    assert len(reports)==3
    assert all(r['guarded_qualified'] and 24.3<r['hz']<24.5 for r in reports)
    assert all(50<=r['frame_interval_ms']<=50.2 for r in reports[1:])
    assert all(r['select_ms']<0.85 and not r['score_parity_checked'] for r in reports)


def test_physical_level_roundtrip_representative_windows():
    # Selected original records: initial quiet, loud peak, lowest overshoot,
    # settled quiet. Gaps are intentional; this is not a recovery-time test.
    reports=list(analyze_fast((Path(__file__).parent/'fixtures/nsdf-fast-low-level-roundtrip.txt').read_text()))
    assert len(reports)==16
    assert all(r['guarded_qualified'] and 24.2<r['hz']<24.7 for r in reports)
    assert min(r['rms_counts'] for r in reports)<7
    assert max(r['rms_counts'] for r in reports)>7000
    assert all(60<r['rms_counts']<70 for r in reports[-3:])
    assert all(not r['score_parity_checked'] for r in reports)


def test_physical_all_bank_schedule_with_normal_ui():
    reports=list(analyze_fast((Path(__file__).parent/'fixtures/nsdf-fast-all-sine-lfo.txt').read_text(),round_robin=True))
    assert len(reports)==32
    for channel in range(4):
        for bank in ('native','low'):
            group=[r for r in reports if (r['channel'],r['bank'])==(channel,bank)]
            assert len(group)==4
            assert all(400<=r['frame_interval_ms']<=400.2 for r in group[1:])
            assert all(r['guarded_qualified']==(channel==0) for r in group)
    assert any(r['channel']==1 and r['qualified'] and not r['device_guard'] for r in reports)
    assert all(b['start_ms']-a['start_ms']==50 for a,b in zip(reports,reports[1:]))
    assert all(r['select_ms']+r['guard_ms']<1.3 for r in reports)
    assert all(not r['score_parity_checked'] for r in reports)
