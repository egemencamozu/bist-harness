"""Turkish display formatting and the inverse parser used by the output validator."""

from __future__ import annotations

from datetime import date

import pytest

from bistharness.core import formatting as fmt


@pytest.mark.parametrize(
    ("value", "kwargs", "expected"),
    [
        (0.123456, {}, "%12,35"),
        (-0.031, {}, "-%3,10"),
        (0.031, {"signed": True}, "+%3,10"),
        (0.0, {"signed": True}, "%0,00"),
        (-0.00001, {}, "%0,00"),
        (7.5215, {}, "%752,15"),
        (12.3456, {"decimals": 1}, "%1.234,6"),
    ],
)
def test_pct(value: float, kwargs: dict, expected: str) -> None:
    assert fmt.pct(value, **kwargs) == expected


def test_numbers_amounts_dates() -> None:
    assert fmt.num(1234.5) == "1.234,50"
    assert fmt.num(-1234567.891, 1) == "-1.234.567,9"
    assert fmt.integer(1926796000) == "1.926.796.000"
    assert fmt.try_amount(662_788_010_000) == "662,79 milyar TL"
    assert fmt.try_amount(-127_640_261_000) == "-127,64 milyar TL"
    assert fmt.try_amount(1.2e12) == "1,20 trilyon TL"
    assert fmt.try_amount(950.0) == "950,00 TL"
    assert fmt.pp(5.49) == "5,49 puan" and fmt.pp_from_fraction(0.0463) == "4,63 puan"
    assert (
        fmt.tr_date(date(2026, 8, 4)) == "04.08.2026" and fmt.tr_datetime("2026-08-04 18:24:32") == "04.08.2026 18:24"
    )
    with pytest.raises(ValueError):
        fmt.num(float("nan"))


def test_parser_reads_back_every_display_format() -> None:
    text = (
        "Getiri %12,35, düşüş -%3,10, artış +%3,10; F/K 11,90; 662,79 milyar TL; 1.926.796.000 hisse; "
        "fark 4,63 puan; 04.08.2026 18:24 tarihinde; 27 işlem günü; XU100 ve RSI(14)."
    )
    assert fmt.numbers_in(text) == [12.35, -3.10, 3.10, 11.90, 662.79, 1_926_796_000, 4.63, 27, 14]
    assert fmt.dates_in(text) == ["04.08.2026"]


@pytest.mark.parametrize("x", [0.0, 0.5, -0.25, 1234.5678, -98765.4321, 3.0])
def test_roundtrip(x: float) -> None:
    assert fmt.numbers_in(fmt.num(x)) == [pytest.approx(round(x, 2))]
    assert fmt.numbers_in(fmt.pct(x / 100)) == [pytest.approx(round(x, 2))]
