"""Unit tests for helao.framework.models.sample_positions models."""

from helao.framework.models.sample_positions import (
    Custom,
    CustomTypes,
    VT15,
    VT54,
    VT70,
    Positions,
)
from helao.framework.models.sample import NoneSample, LiquidSample


def test_custom_construction():
    """Test Custom position construction and basic properties."""
    custom = Custom(
        custom_name="test_cell",
        custom_type=CustomTypes.cell,
    )

    assert custom.custom_name == "test_cell"
    assert custom.custom_type == CustomTypes.cell
    assert custom.blocked is False
    assert isinstance(custom.sample, NoneSample)


def test_custom_assembly_allowed():
    """Test assembly_allowed() method on Custom positions."""
    cell = Custom(custom_name="cell1", custom_type=CustomTypes.cell)
    reservoir = Custom(custom_name="res1", custom_type=CustomTypes.reservoir)

    assert cell.assembly_allowed() is True
    assert reservoir.assembly_allowed() is False


def test_custom_dest_allowed():
    """Test dest_allowed() method on Custom positions."""
    cell = Custom(custom_name="cell1", custom_type=CustomTypes.cell)
    injector = Custom(custom_name="inj1", custom_type=CustomTypes.injector)
    reservoir = Custom(custom_name="res1", custom_type=CustomTypes.reservoir)

    assert cell.dest_allowed() is True
    assert injector.dest_allowed() is True
    assert reservoir.dest_allowed() is False


def test_custom_is_destroyed():
    """Test is_destroyed() method on Custom positions."""
    injector = Custom(custom_name="inj1", custom_type=CustomTypes.injector)
    waste = Custom(custom_name="waste1", custom_type=CustomTypes.waste)
    cell = Custom(custom_name="cell1", custom_type=CustomTypes.cell)

    assert injector.is_destroyed() is True
    assert waste.is_destroyed() is True
    assert cell.is_destroyed() is False


def test_vt15_construction():
    """Test VT15 vial tray construction."""
    vt = VT15()

    assert vt.VTtype == "VT15"
    assert vt.positions == 15
    assert vt.max_vol_ml == 10.0
    assert len(vt.vials) == 15
    assert len(vt.samples) == 15
    assert all(not v for v in vt.vials)  # all empty


def test_vt54_construction():
    """Test VT54 vial tray construction."""
    vt = VT54()

    assert vt.VTtype == "VT54"
    assert vt.positions == 54
    assert vt.max_vol_ml == 2.0
    assert len(vt.vials) == 54


def test_vt70_construction():
    """Test VT70 vial tray construction."""
    vt = VT70()

    assert vt.VTtype == "VT70"
    assert vt.positions == 70
    assert vt.max_vol_ml == 1.0
    assert len(vt.vials) == 70


def test_vt_first_empty():
    """Test first_empty() method."""
    vt = VT15()
    vt.vials = [False, False, True, False, False]

    # Reset for proper length
    vt.reset_tray()
    vt.vials[2] = True

    first = vt.first_empty()
    assert first == 0  # First empty should be 0


def test_vt_first_full():
    """Test first_full() method."""
    vt = VT15()
    vt.reset_tray()
    vt.vials[5] = True

    first = vt.first_full()
    assert first == 5


def test_vt_load_sample():
    """Test loading a sample into a vial."""
    vt = VT15()
    sample = LiquidSample(global_label="test_liquid")

    result = vt.load(sample, vial=1)
    assert result != NoneSample()
    assert vt.vials[0] is True  # 1-indexed becomes 0-indexed


def test_positions_container():
    """Test Positions container with customs and trays."""
    custom1 = Custom(custom_name="cell1", custom_type=CustomTypes.cell)
    custom2 = Custom(custom_name="waste1", custom_type=CustomTypes.waste)
    vt = VT15()

    positions = Positions(
        customs_dict={
            "cell1": custom1,
            "waste1": custom2,
        },
        trays_dict={
            0: {0: vt},
        },
    )

    assert "cell1" in positions.customs_dict
    assert "waste1" in positions.customs_dict
    assert 0 in positions.trays_dict
    assert 0 in positions.trays_dict[0]


def test_custom_as_dict():
    """Test Custom.as_dict() (from HelaoDict)."""
    custom = Custom(
        custom_name="test_cell",
        custom_type=CustomTypes.cell,
    )

    d = custom.as_dict()
    assert isinstance(d, dict)
    assert "custom_name" in d
    assert "custom_type" in d
    assert d["custom_name"] == "test_cell"
