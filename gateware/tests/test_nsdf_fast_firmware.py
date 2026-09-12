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


@pytest.mark.parametrize('mode',['full','fast-native','fast-low'])
def test_real_trace_state_machine_bounded_uart_and_cadence(tmp_path,mode):
    here=Path(__file__).parent;exe=tmp_path/'trace'
    rustc=shutil.which('rustc') or str(Path.home()/'.cargo/bin/rustc')
    env=dict(os.environ,TILIQUA_TUNER_NSDF_TRACE=mode)
    subprocess.run([rustc,'--edition=2021','-O',str(here/'nsdf_trace_mock.rs'),'-o',str(exe)],env=env,check=True)
    output=subprocess.check_output([exe],text=True)
    if mode!='full':
        reports=list(analyze_fast(output))
        assert len(reports)>100 and all(r['guarded_qualified'] for r in reports)
        # UART backpressure stretches cadence; never fabricate a fixed rate.
        assert max(r['frame_interval_ms'] or 0 for r in reports)>300
        assert all(not r['score_parity_checked'] for r in reports)


def test_physical_buffered_quiet_low_summaries_reach_20hz():
    reports=list(analyze_fast((Path(__file__).parent/'fixtures/nsdf-fast-low-buffered-steady.txt').read_text()))
    assert len(reports)==3
    assert all(r['guarded_qualified'] and 24.3<r['hz']<24.5 for r in reports)
    assert all(50<=r['frame_interval_ms']<=50.2 for r in reports[1:])
    assert all(r['select_ms']<0.85 and not r['score_parity_checked'] for r in reports)
