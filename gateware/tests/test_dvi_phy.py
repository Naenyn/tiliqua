from amaranth.hdl import Fragment
import pytest

from tiliqua.video.dvi import DVIPHY


def test_split_load_strobes_allow_floorplanned_serializer_lanes():
    lane_x = (70, 49, 60, 65)
    phy = DVIPHY(split_load_strobes=True, serializer_lane_x=lane_x)

    assert phy.split_load_strobes
    assert not phy.local_phase_rings
    assert phy.serializer_lane_x == lane_x
    Fragment.get(phy, platform=None)


def test_upper_load_strobes_share_the_upper_data_row_without_bel_collision():
    lane_x = (70, 49, 60, 65)
    phy = DVIPHY(split_load_strobes=True, serializer_lane_x=lane_x,
                 colocate_upper_load_strobes=True)
    fragment = Fragment.get(phy, platform=None)
    strobes = [child.attrs['BEL'] for child, *_ in fragment.subfragments
               if getattr(child, 'type', None) == 'FD1S3AX']
    assert strobes == [location for x in lane_x for location in
                      (f'X{x}/Y2/SLICEA.FF0', f'X{x}/Y4/SLICEB.FF0')]
    assert len(set(strobes)) == 8
    assert not phy.local_phase_rings


def test_colocated_upper_strobes_require_a_split_floorplan():
    with pytest.raises(ValueError, match='floorplanned split'):
        DVIPHY(colocate_upper_load_strobes=True)
