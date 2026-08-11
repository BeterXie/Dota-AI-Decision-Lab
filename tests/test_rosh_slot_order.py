from types import SimpleNamespace

import pytest

from app.draft.rosh_service import _ordered_slots


def test_rosh_slots_are_radiant_then_dire_by_position() -> None:
    slots = [
        SimpleNamespace(side=side, position=position, hero_id=hero_id)
        for side, position, hero_id in (
            ("dire", 3, 103),
            ("radiant", 5, 5),
            ("dire", 1, 101),
            ("radiant", 1, 1),
            ("dire", 5, 105),
            ("radiant", 3, 3),
            ("dire", 2, 102),
            ("radiant", 4, 4),
            ("dire", 4, 104),
            ("radiant", 2, 2),
        )
    ]

    radiant, dire = _ordered_slots(slots)

    assert [slot.hero_id for slot in radiant] == [1, 2, 3, 4, 5]
    assert [slot.hero_id for slot in dire] == [101, 102, 103, 104, 105]


def test_rosh_slot_order_rejects_missing_position() -> None:
    slots = [SimpleNamespace(side="radiant", position=position) for position in (1, 2, 3, 4, 4)] + [
        SimpleNamespace(side="dire", position=position) for position in range(1, 6)
    ]

    with pytest.raises(ValueError, match="DRAFT_PARTIAL"):
        _ordered_slots(slots)
