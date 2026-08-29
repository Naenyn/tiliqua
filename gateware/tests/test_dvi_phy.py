from amaranth.hdl import Fragment

from tiliqua.video.dvi import DVIPHY


def test_split_load_strobes_allow_floorplanned_serializer_lanes():
    lane_x = (70, 49, 60, 65)
    phy = DVIPHY(split_load_strobes=True, serializer_lane_x=lane_x)

    assert phy.split_load_strobes
    assert not phy.local_phase_rings
    assert phy.serializer_lane_x == lane_x
    Fragment.get(phy, platform=None)
