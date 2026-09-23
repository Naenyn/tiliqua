"""Exercise the actual TUNER archive callback without elaborating a SoC."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('external',[False,True])
def test_archive_disables_spread_without_changing_clocks_or_storage(external):
    source=Path(__file__).parents[1]/'src/top/intono/top.py'
    tree=ast.parse(source.read_text())
    callback=next(n for n in tree.body if isinstance(n,ast.FunctionDef)
                  and n.name=='configure_archive')
    namespace={}
    exec(compile(ast.Module(body=[callback],type_ignores=[]),str(source),'exec'),namespace)
    config=SimpleNamespace(clk0_hz=49152000,clk1_hz=74250000,
                           clk1_inherit=False,spread_spectrum=0.01) if external else None
    sizes=[]
    archive=SimpleNamespace(external_pll_config=config,
                            with_option_storage=lambda **kw:sizes.append(kw['size']))
    namespace['configure_archive'](archive)
    assert sizes==[24576]
    if external:
        assert vars(config)==dict(clk0_hz=49152000,clk1_hz=74250000,
                                  clk1_inherit=False,spread_spectrum=0.0)
    else:
        assert archive.external_pll_config is None
