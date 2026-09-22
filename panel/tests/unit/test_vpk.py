from l4d2panel.integrations.vpk import VPK_MAGIC, vpk_entries
from tests.fakes.vpk import build_vpk


def test_roundtrip(tmp_path):
    p = tmp_path / 'a.vpk'; p.write_bytes(build_vpk(['maps/m1.bsp', 'maps/m2.bsp', 'missions/x.txt', 'root.txt']))
    assert p.read_bytes()[:4] == VPK_MAGIC
    assert vpk_entries(p) == ['maps/m1.bsp', 'maps/m2.bsp', 'missions/x.txt', 'root.txt']


def test_not_a_vpk(tmp_path):
    p = tmp_path / 'b.vpk'; p.write_bytes(b'hello world, not a vpk')
    assert vpk_entries(p) == []
    assert vpk_entries(tmp_path / 'missing.vpk') == []
