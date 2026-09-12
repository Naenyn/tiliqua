import os
from pathlib import Path
import shutil
import subprocess
import pytest
from analyze_nsdf_fast import analyze_fast


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
