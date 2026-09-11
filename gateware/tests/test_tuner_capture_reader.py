"""Host-side transport regressions; never open a physical serial port."""
import json
from types import SimpleNamespace
import capture_tuner


def test_ready_handshake_and_complete_capture(monkeypatch,tmp_path,capsys):
    samples=[n-1024 for n in range(2048)]
    stream=("\nCAPTURE READY\nCAL STATUS FAILED - NOT TRACKING\nCAPTURE STATUS UNAVAILABLE - HISTORY NOT FULL\n\nCAPTURE BEGIN fs=192000 div=1 lag=6400 raw=7680 factor=2 error=1 span=2\n"
            +"".join(f"{n & 65535:04X}\n" for n in samples)+"CAPTURE END\n").encode()
    class Link:
        def __init__(self,**kwargs):
            assert kwargs["baudrate"]==115200
            self.data=stream
        def open(self):
            assert self.dtr is True and self.rts is False
            assert self.port=="test-only"
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,count):
            # Deliberately split lines across reads.
            chunk,self.data=self.data[:37],self.data[37:]
            return chunk
    monkeypatch.setattr(capture_tuner.serial,"Serial",Link)
    monkeypatch.setattr(capture_tuner,"comports",lambda:[SimpleNamespace(vid=0x1209,pid=0xc0ca,device="test-only")])
    output=tmp_path/"capture.json"
    monkeypatch.setattr("sys.argv",["capture_tuner","--output",str(output)])
    capture_tuner.main()
    assert json.loads(output.read_text())["samples"]==samples
    assert "diagnostic link confirmed" in capsys.readouterr().out
    transcript=output.with_suffix(".serial.log").read_text()
    assert "CAL STATUS FAILED - NOT TRACKING" in transcript
    assert "CAPTURE STATUS UNAVAILABLE - HISTORY NOT FULL" in transcript
    assert "CAPTURE END" in transcript
