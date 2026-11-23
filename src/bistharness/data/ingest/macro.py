"""Macro ingest without API keys (CLAUDE.md §11, §14): official TCMB pages/files + FRED public CSV.

Series (macro_observations.series_code) and their knowledge time (`release_datetime`, Europe/Istanbul local):

* USDTRY, EURTRY — TCMB indicative rates (ForexBuying, "gösterge niteliğindeki döviz alış kuru"), daily XML
  `tcmb.gov.tr/kurlar/YYYYMM/DDMMYYYY.xml`, set and published at 15:30 on the bulletin date.
* TCMB_POLICY_RATE — one-week repo rate (%), TCMB "1 Hafta Repo" table. The table lists the EFFECTIVE date (the day
  after the MPC decision announced at 14:00); release is taken as the effective date 00:00 — conservative by at most
  one day, never early.
* FED_TARGET_UPPER, FED_TARGET_LOWER — FRED DFEDTARU / DFEDTARL (daily, values change on the effective date, the day
  after the FOMC statement at 14:00 ET = 21:00/22:00 Istanbul). Only change points are stored; release = effective
  date 00:00 (conservative).
* TUFE_YOY, TUFE_MOM — TÜİK CPI (% change) as tabulated by TCMB "Tüketici Fiyatları". TÜİK publishes on the 3rd of
  the following month at 10:00, moved to the next working day on weekends/holidays; release = first BIST trading day
  on or after the 3rd, 10:00 (trading calendar from the price ingest; weekday rule beyond it).

Snapshot `D` keeps only observations released before day `D`. Raw responses are frozen under `data/raw/<source>/<D>/`
with a sha256 manifest; re-runs verify the manifest and never download again.
"""

from __future__ import annotations

import csv
import http.client
import io
import logging
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd

from bistharness import __version__
from bistharness.core.config import Settings
from bistharness.core.errors import DataNotFoundError
from bistharness.core.hashing import sha256_hex
from bistharness.data import db
from bistharness.data.ingest import manifest as mf

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (educational research data ingest)"
TCMB_FX_URL = "https://www.tcmb.gov.tr/kurlar/{yyyymm}/{ddmmyyyy}.xml"
TCMB_REPO_URL = (
    "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Temel+Faaliyetler/Para+Politikasi/"
    "Merkez+Bankasi+Faiz+Oranlari/1+Hafta+Repo"
)
TCMB_CPI_URL = (
    "https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Istatistikler/Enflasyon+Verileri/Tuketici+Fiyatlari"
)
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_SERIES = {"DFEDTARU": "FED_TARGET_UPPER", "DFEDTARL": "FED_TARGET_LOWER"}
FX_CODES = {"USD": "USDTRY", "EUR": "EURTRY"}
FX_RELEASE_TIME = "15:30:00"
CPI_RELEASE_TIME = "10:00:00"


@dataclass(frozen=True)
class Observation:
    series_code: str
    obs_date: str  # YYYY-MM-DD (month start for monthly series)
    value: float
    release_datetime: str  # YYYY-MM-DD HH:MM:SS Europe/Istanbul
    source: str
    source_ref: str


# --------------------------------------------------------------------------- HTTP (ingest only)
def fetch(url: str, *, retries: int = 5, pause: float = 3.0, timeout: float = 30.0) -> bytes | None:
    """GET with retries. Returns None on HTTP 404 (TCMB has no file for non-business days)."""
    # FRED drops requests without an Accept header (RemoteDisconnected), observed 2026-11-21
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body: bytes = resp.read()
                return body
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            log.warning("HTTP %s for %s (attempt %d)", exc.code, url, attempt)
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:  # incl. dropped connections
            log.warning("%s for %s (attempt %d)", exc, url, attempt)
        time.sleep(pause * attempt)
    raise DataNotFoundError(f"could not download {url}")


# --------------------------------------------------------------------------- pure parsers
class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def html_table_rows(html: str) -> list[list[str]]:
    p = _TableParser()
    p.feed(html)
    return p.rows


def _num(s: str) -> float | None:
    s = s.strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_policy_rates(html: str) -> list[tuple[date, float]]:
    """(effective date, one-week repo lending rate %) from the TCMB '1 Hafta Repo' table."""
    out: list[tuple[date, float]] = []
    for row in html_table_rows(html):
        if len(row) < 2:
            continue
        try:
            d = datetime.strptime(row[0].strip(), "%d.%m.%Y").date()
        except ValueError:
            continue
        rate = _num(row[-1])
        if rate is not None:
            out.append((d, rate))
    return sorted(set(out))


def parse_cpi(html: str) -> list[tuple[date, float, float]]:
    """(month start, CPI YoY %, CPI MoM %) from the TCMB 'Tüketici Fiyatları' table (rows like '10-2026')."""
    out: list[tuple[date, float, float]] = []
    for row in html_table_rows(html):
        if len(row) < 3:
            continue
        try:
            month = datetime.strptime(row[0].strip(), "%m-%Y").date()
        except ValueError:
            continue
        yoy, mom = _num(row[1]), _num(row[2])
        if yoy is not None and mom is not None:
            out.append((month, yoy, mom))
    return sorted(set(out))


def parse_tcmb_fx_xml(content: bytes) -> tuple[date, dict[str, float]]:
    root = ET.fromstring(content)
    d = datetime.strptime(str(root.attrib["Tarih"]), "%d.%m.%Y").date()
    rates: dict[str, float] = {}
    for cur in root.findall("Currency"):
        code = cur.attrib.get("CurrencyCode") or cur.attrib.get("Kod")
        unit = _num(cur.findtext("Unit") or "1") or 1.0
        buying = _num(cur.findtext("ForexBuying") or "")
        if code in FX_CODES and buying is not None:
            rates[code] = buying / unit
    return d, rates


def parse_fred_csv(text: str) -> pd.Series:
    rows = list(csv.reader(io.StringIO(text)))
    data = {r[0]: _num(r[1]) for r in rows[1:] if len(r) >= 2 and _num(r[1]) is not None}
    s = pd.Series(data, dtype=float)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def change_points(s: pd.Series) -> pd.Series:
    """First observation plus every observation whose value differs from the previous one."""
    s = s.dropna()
    return s[s.ne(s.shift(1))]


def cpi_release(month: date, trading_days: Sequence[date]) -> str:
    """TÜİK release of `month`'s CPI: 3rd of the next month, or the next BIST trading day, at 10:00."""
    nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    third = nxt.replace(day=3)
    later = [d for d in trading_days if d >= third]
    if later:
        rel = later[0]
    else:  # beyond the known calendar: next weekday
        rel = third
        while rel.weekday() >= 5:
            rel += timedelta(days=1)
    return f"{rel.isoformat()} {CPI_RELEASE_TIME}"


def weekdays(start: date, end_exclusive: date) -> Iterable[date]:
    d = start
    while d < end_exclusive:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


# --------------------------------------------------------------------------- observations from a frozen snapshot
def fx_observations(fx_dir: Path) -> list[Observation]:
    out: list[Observation] = []
    for path in sorted(fx_dir.glob("*.xml")):
        d, rates = parse_tcmb_fx_xml(path.read_bytes())
        if path.stem != d.strftime("%Y%m%d"):
            raise DataNotFoundError(f"{path.name}: bulletin date {d} does not match the requested day")
        for code, value in sorted(rates.items()):
            out.append(
                Observation(
                    FX_CODES[code],
                    d.isoformat(),
                    value,
                    f"{d.isoformat()} {FX_RELEASE_TIME}",
                    "tcmb_fx",
                    f"tcmb:kurlar/{d.strftime('%Y%m')}/{d.strftime('%d%m%Y')}.xml",
                )
            )
    return out


def policy_observations(html: str) -> list[Observation]:
    return [
        Observation(
            "TCMB_POLICY_RATE", d.isoformat(), r, f"{d.isoformat()} 00:00:00", "tcmb_rates", "tcmb:1-hafta-repo"
        )
        for d, r in parse_policy_rates(html)
    ]


def cpi_observations(html: str, trading_days: Sequence[date]) -> list[Observation]:
    out: list[Observation] = []
    for month, yoy, mom in parse_cpi(html):
        rel = cpi_release(month, trading_days)
        ref = f"tcmb:tuketici-fiyatlari#{month.strftime('%m-%Y')}"
        out.append(Observation("TUFE_YOY", month.isoformat(), yoy, rel, "tuik_via_tcmb", ref))
        out.append(Observation("TUFE_MOM", month.isoformat(), mom, rel, "tuik_via_tcmb", ref))
    return out


def fred_observations(series_id: str, text: str) -> list[Observation]:
    code = FRED_SERIES[series_id]
    return [
        Observation(
            code, ts.date().isoformat(), float(v), f"{ts.date().isoformat()} 00:00:00", "fred", f"fred:{series_id}"
        )
        for ts, v in change_points(parse_fred_csv(text)).items()
    ]


# --------------------------------------------------------------------------- snapshot + ingest
FX_SOURCE, RATES_SOURCE, FRED_SOURCE = "tcmb_fx", "tcmb_rates", "fred"
FX_START = date(2022, 12, 1)  # matches the price history start
FX_PAUSE_SECONDS = 0.25


def prepare_fx_snapshot(settings: Settings, snapshot: str, *, allow_download: bool) -> dict[str, object]:
    dest = settings.raw_dir / FX_SOURCE / snapshot
    if (dest / mf.MANIFEST_NAME).exists():
        return mf.verify_manifest(dest)
    if not allow_download:
        raise DataNotFoundError(f"TCMB FX snapshot {dest} missing and downloads are disabled")
    dest.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for d in weekdays(FX_START, date.fromisoformat(snapshot)):
        target = dest / f"{d.strftime('%Y%m%d')}.xml"
        if target.exists():  # resume an interrupted download
            continue
        body = fetch(TCMB_FX_URL.format(yyyymm=d.strftime("%Y%m"), ddmmyyyy=d.strftime("%d%m%Y")))
        if body is None:
            missing.append(d.isoformat())
        else:
            target.write_bytes(body)
        time.sleep(FX_PAUSE_SECONDS)
    (dest / "no_bulletin_days.txt").write_text("\n".join(missing) + "\n", encoding="utf-8")
    params = {
        "url": TCMB_FX_URL,
        "start": FX_START.isoformat(),
        "end_exclusive": snapshot,
        "no_bulletin_days": len(missing),
    }
    return mf.write_manifest(dest, source=FX_SOURCE, params=params)


def prepare_page_snapshot(
    settings: Settings, source: str, snapshot: str, urls: dict[str, str], *, allow_download: bool
) -> dict[str, object]:
    dest = settings.raw_dir / source / snapshot
    if (dest / mf.MANIFEST_NAME).exists():
        return mf.verify_manifest(dest)
    if not allow_download:
        raise DataNotFoundError(f"{source} snapshot {dest} missing and downloads are disabled")
    files: dict[str, bytes] = {}
    for name, url in urls.items():
        body = fetch(url)
        if body is None:
            raise DataNotFoundError(f"{url} returned 404")
        files[name] = body
    dest.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (dest / name).write_bytes(body)
    return mf.write_manifest(dest, source=source, params={"urls": urls, "downloaded_for_snapshot": snapshot})


@dataclass
class MacroSummary:
    ingest_id: str
    snapshot: str
    per_series: pd.DataFrame  # series_code, n, first_obs, last_obs, last_release


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def run(settings: Settings, snapshot: str, *, allow_download: bool = True) -> MacroSummary:
    started = _now()
    fx_m = prepare_fx_snapshot(settings, snapshot, allow_download=allow_download)
    rates_m = prepare_page_snapshot(
        settings,
        RATES_SOURCE,
        snapshot,
        {"one_week_repo.html": TCMB_REPO_URL, "cpi.html": TCMB_CPI_URL},
        allow_download=allow_download,
    )
    fred_m = prepare_page_snapshot(
        settings,
        FRED_SOURCE,
        snapshot,
        {f"{s}.csv": FRED_URL.format(series=s) for s in FRED_SERIES},
        allow_download=allow_download,
    )
    rates_dir = settings.raw_dir / RATES_SOURCE / snapshot
    fred_dir = settings.raw_dir / FRED_SOURCE / snapshot

    conn = db.connect(settings.db_path)
    try:
        db.init_db(conn)
        trading_days = [
            date.fromisoformat(r[0]) for r in conn.execute("SELECT date FROM trading_calendar ORDER BY date")
        ]
        obs = [
            *fx_observations(settings.raw_dir / FX_SOURCE / snapshot),
            *policy_observations((rates_dir / "one_week_repo.html").read_text(encoding="utf-8")),
            *cpi_observations((rates_dir / "cpi.html").read_text(encoding="utf-8"), trading_days),
        ]
        for series in FRED_SERIES:
            obs += fred_observations(series, (fred_dir / f"{series}.csv").read_text(encoding="utf-8"))
        cutoff = f"{snapshot} 00:00:00"
        obs = sorted((o for o in obs if o.release_datetime < cutoff), key=lambda o: (o.series_code, o.obs_date))
        version = sha256_hex([fx_m["content_sha256"], rates_m["content_sha256"], fred_m["content_sha256"]])
        ingest_id = f"macro-{snapshot}-{version[:10]}"
        conn.execute("DELETE FROM macro_observations")
        conn.executemany(
            "INSERT INTO macro_observations VALUES (?,?,?,?,?,?,?)",
            [(o.series_code, o.obs_date, o.value, o.release_datetime, o.source, o.source_ref, ingest_id) for o in obs],
        )
        conn.execute(
            "INSERT OR REPLACE INTO ingest_log VALUES (?,?,?,?,?,?,?,?,?)",
            (ingest_id, "macro", snapshot, version, len(obs), "{}", started, _now(), __version__),
        )
        conn.commit()
    finally:
        conn.close()
    df = pd.DataFrame([o.__dict__ for o in obs])
    per = (
        df.groupby("series_code")
        .agg(
            n=("value", "size"),
            first_obs=("obs_date", "min"),
            last_obs=("obs_date", "max"),
            last_value=("value", "last"),
            last_release=("release_datetime", "max"),
        )
        .reset_index()
    )
    return MacroSummary(ingest_id=ingest_id, snapshot=snapshot, per_series=per)


__all__ = [
    "FRED_SERIES",
    "MacroSummary",
    "Observation",
    "change_points",
    "cpi_observations",
    "cpi_release",
    "fetch",
    "fred_observations",
    "fx_observations",
    "html_table_rows",
    "parse_cpi",
    "parse_fred_csv",
    "parse_policy_rates",
    "parse_tcmb_fx_xml",
    "policy_observations",
    "prepare_fx_snapshot",
    "prepare_page_snapshot",
    "run",
    "weekdays",
]
