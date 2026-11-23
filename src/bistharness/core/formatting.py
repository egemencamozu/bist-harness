"""Turkish display formatting for evidence values, and the inverse parser used by the output validator.

Every number an explanation may quote comes from a `display` string produced here (CLAUDE.md §1.2, §4):
- percentages:  0.123456 -> "%12,35"; negative "-%3,10"; signed=True adds "+" ("+%3,10")
- numbers:      1234.5 -> "1.234,50"; integers "1.234"
- TRY amounts:  662_788_010_000 -> "662,79 milyar TL" (milyon / milyar / trilyon)
- points:       5.49 (already in percent units) -> "5,49 puan"; fraction differences via `pp_from_fraction`
- multiples:    11.8964 -> "11,90" (F/K, PD/DD ... shown without a unit sign)
- dates:        2026-08-04 -> "04.08.2026"
The parser (`numbers_in`) returns every numeric value written in Turkish (or plain) notation in a text, with dates
removed first so "04.08.2026" is not read as numbers.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime

_SCALES = ((1e12, "trilyon"), (1e9, "milyar"), (1e6, "milyon"))


def _group(int_part: str) -> str:
    out: list[str] = []
    while len(int_part) > 3:
        out.insert(0, int_part[-3:])
        int_part = int_part[:-3]
    out.insert(0, int_part)
    return ".".join(out)


def num(x: float, decimals: int = 2) -> str:
    if x is None or not math.isfinite(x):
        raise ValueError(f"cannot format {x!r}")
    neg = x < 0 and round(abs(x), decimals) != 0
    s = f"{abs(x):.{decimals}f}"
    int_part, _, frac = s.partition(".")
    body = _group(int_part) + ("," + frac if decimals > 0 else "")
    return ("-" if neg else "") + body


def integer(n: int | float) -> str:
    return num(float(n), 0)


def pct(x: float, decimals: int = 2, *, signed: bool = False) -> str:
    """Fraction -> Turkish percent: 0.1235 -> "%12,35"."""
    v = x * 100
    body = num(abs(v), decimals)
    if v < 0 and round(abs(v), decimals) != 0:
        return "-%" + body
    return ("+%" if signed and round(v, decimals) != 0 else "%") + body


def pp(points: float, decimals: int = 2) -> str:
    """Value already in percentage points -> "5,49 puan"."""
    return f"{num(points, decimals)} puan"


def pp_from_fraction(diff: float, decimals: int = 2) -> str:
    """Difference of two fractions (0.0434) -> "4,34 puan"."""
    return pp(diff * 100, decimals)


def try_amount(x: float, decimals: int = 2) -> str:
    a = abs(x)
    for scale, word in _SCALES:
        if a >= scale:
            return f"{num(x / scale, decimals)} {word} TL"
    return f"{num(x, decimals)} TL"


def multiple(x: float, decimals: int = 2) -> str:
    return num(x, decimals)


def tr_date(d: date | datetime | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    return d.strftime("%d.%m.%Y")


def tr_datetime(s: str) -> str:
    """'2026-08-04 18:24:32' -> '04.08.2026 18:24'."""
    return f"{tr_date(s)} {s[11:16]}" if len(s) >= 16 else tr_date(s)


# ----------------------------------------------------------------------------------------------- parsing
_DATE_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{4}\b|\b\d{4}-\d{2}-\d{2}\b")
_FISCAL_RE = re.compile(r"\b(\d{4})(?:Ç|Q)[1-4]\b")
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
# thousands-grouped (1.234.567,89) | decimal comma (12,35) | plain (12 / 12.5 in English notation)
_NUM_RE = re.compile(r"(?<![\w.,])[-+]?%?[-+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?|(?<![\w.,])[-+]?%?[-+]?\d+(?:[.,]\d+)?")


def _to_float(tok: str) -> float:
    t = tok.replace("%", "")
    sign = -1.0 if t.count("-") % 2 else 1.0
    t = t.replace("-", "").replace("+", "")
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):
        t = t.replace(".", "").replace(",", ".")
    else:
        t = t.replace(",", ".")
    return sign * float(t)


def typed_numbers_in(text: str) -> list[tuple[str, float]]:
    """Like numbers_in, but each value carries its kind: "pct" when written with a percent sign, else "num".
    The validator compares kinds, so a count shown as "31" cannot be quoted as "%31"."""
    cleaned = _TIME_RE.sub(" ", _DATE_RE.sub(" ", text))
    return [("pct" if "%" in m.group(0) else "num", _to_float(m.group(0))) for m in _NUM_RE.finditer(cleaned)]


def years_in(text: str) -> set[int]:
    """Years of the dates written in a text (DD.MM.YYYY or ISO) and of fiscal labels like 2026Ç2 / 2026Q2."""
    out = {int(d[-4:]) if "." in d else int(d[:4]) for d in _DATE_RE.findall(text)}
    out |= {int(y) for y in _FISCAL_RE.findall(text)}
    return out


def dates_in(text: str) -> list[str]:
    return _DATE_RE.findall(text)


def numbers_in(text: str) -> list[float]:
    """Numeric values written in the text (dates and clock times excluded)."""
    cleaned = _TIME_RE.sub(" ", _DATE_RE.sub(" ", text))
    return [_to_float(m.group(0)) for m in _NUM_RE.finditer(cleaned)]
