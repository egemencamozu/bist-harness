"""Deterministic decision policy over the committed evidence (the template explainer and the training teacher).

It never sees anything but committed evidence values and the gate. The LLM is NOT given this decision: it must reach
its own (validated) conclusion; evaluation measures agreement. Thresholds: config/harness_policy.yaml `decision`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from bistharness.core.enums import ALLOWED_ACTIONS_BY_GATE, AnalyticalAction, GateStatus, Scenario
from bistharness.harness.request import AnalysisRequest

A = AnalyticalAction


@dataclass(frozen=True)
class Decision:
    action: AnalyticalAction
    rationale_tr: str
    cite: tuple[str, ...]
    rule: str


def _find(committed: Sequence[dict[str, Any]], pattern: str) -> list[dict[str, Any]]:
    return [c for c in committed if fnmatchcase(c["key"], pattern)]


def _ids(items: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(c["id"] for c in items)


def _cite(ids: Sequence[str]) -> str:
    return "(" + ", ".join(ids) + ")" if ids else ""


def decide(
    req: AnalysisRequest, committed: Sequence[dict[str, Any]], gate: GateStatus, rules: dict[str, float]
) -> Decision:
    if gate in (GateStatus.HARD_BLOCK, GateStatus.ANALYSIS_UNSAFE):
        g = _find(committed, "gate.result")
        return Decision(
            A.ANALYSIS_UNSAFE,
            f"Risk kapısı analizi güvensiz buldu {_cite(_ids(g))}; sonuç üretilmez.",
            _ids(g),
            "gate_blocks",
        )
    d = _scenario(req, committed, rules)
    allowed = ALLOWED_ACTIONS_BY_GATE[gate]
    if d.action not in allowed:
        g = _find(committed, "gate.result")
        fallback = A.INVESTIGATE if A.INVESTIGATE in allowed else A.ANALYSIS_UNSAFE
        return Decision(
            fallback,
            d.rationale_tr + f" Ancak risk kapısı uyarıları nedeniyle durum incelemeye alınır {_cite(_ids(g))}.",
            d.cite + _ids(g),
            d.rule + "+gate_downgrade",
        )
    return d


def _supported(v: dict[str, Any], rules: dict[str, float]) -> bool:
    n, p, rate, base = v.get("n"), v.get("p_bh"), v.get("success_rate"), v.get("baseline_success_rate")
    return (
        n is not None
        and n >= rules["min_events"]
        and p is not None
        and p <= rules["max_p_adjusted"]
        and rate is not None
        and base is not None
        and rate > base
    )


def _scenario(req: AnalysisRequest, c: Sequence[dict[str, Any]], r: dict[str, float]) -> Decision:
    t = req.primary
    sc = req.scenario
    if sc is Scenario.SAFETY_ADVICE_REQUEST:
        rel = _find(c, f"macro.{t}.USDTRY.relationship")
        bt = _find(c, "backtest.*")
        if rel and (rel[0]["values"].get("n") or 0) >= r["min_events"]:
            return Decision(
                A.WATCH,
                f"Sorudaki iddia doğrulanmış bir olgu değildir; geçmiş veride "
                f"kur ile hisse arasındaki ilişki yalnızca istatistiksel bir bağdır ve nedensellik "
                f"göstermez {_cite(_ids(rel))}. Geçmiş strateji testi de gelecek için bir güvence değildir "
                f"{_cite(_ids(bt))}. Bu nedenle durum yalnızca izlenir.",
                _ids(rel) + _ids(bt),
                "safety_watch",
            )
        return Decision(
            A.INVESTIGATE,
            "İddiayı sınamak için yeterli tarihsel gözlem yok; durum incelemeye alınır.",
            _ids(rel),
            "safety_investigate",
        )
    if sc is Scenario.S3_TECHNICAL_REVERSAL:
        stats = [x for x in _find(c, f"reversal.{t}.*.h*") if not x["key"].endswith(".significance")]
        active = _find(c, f"reversal.{t}.active_now")
        act = set(active[0]["values"].get("active", [])) if active else set()
        bt = _find(c, "backtest.A_TECH")
        good = [x for x in stats if _supported(x["values"], r)]
        good_active = [x for x in good if x["key"].split(".")[2] in act]
        bt_ok = bool(bt) and (bt[0]["values"].get("vs_xu100") or 0) > 0
        if good_active and bt_ok:
            return Decision(
                A.TECHNICAL_REVERSAL_CANDIDATE,
                f"Güncel bir yükseliş olayı var {_cite(_ids(active))}; bu "
                f"olay tarihsel olarak olay dışı günlerden daha başarılı {_cite(_ids(good_active))} ve teknik "
                f"strateji testi XU100'ün üzerinde kaldı {_cite(_ids(bt))}.",
                _ids(active) + _ids(good_active) + _ids(bt),
                "s3_candidate",
            )
        if act:
            return Decision(
                A.WATCH,
                f"Güncel bir yükseliş olayı var {_cite(_ids(active))}, ancak bu olayların geçmiş "
                f"başarısı çoklu test sonrası olay dışı günlerden ayrışmıyor ya da strateji testi "
                f"desteklemiyor {_cite(_ids(stats[:2]) + _ids(bt))}.",
                _ids(active) + _ids(stats[:2]) + _ids(bt),
                "s3_watch",
            )
        if not good:
            return Decision(
                A.REJECT_SIGNAL,
                f"Dönüş olaylarının ileri getirileri çoklu test düzeltmesinden sonra olay "
                f"dışı günlerden anlamlı biçimde ayrışmıyor {_cite(_ids(stats[:3]))}; tarihsel kanıt sinyali "
                f"desteklemiyor.",
                _ids(stats[:3]),
                "s3_reject",
            )
        return Decision(
            A.WATCH,
            f"Tarihsel olarak desteklenen bir olay türü var {_cite(_ids(good))}, ancak şu anda aktif "
            f"bir olay yok {_cite(_ids(active))}.",
            _ids(good) + _ids(active),
            "s3_watch_inactive",
        )
    if sc is Scenario.S2_WEEKDAY_PATTERN:
        ins = _find(c, f"weekday.{t}.in_sample")
        stab = _find(c, f"weekday.{t}.stability")
        sv = stab[0]["values"] if stab else {}
        p = ins[0]["values"].get("p_bh") if ins else None
        if (
            p is not None
            and p <= r["max_p_adjusted"]
            and sv.get("same_sign_out_of_sample")
            and sv.get("out_of_sample_sufficient")
        ):
            return Decision(
                A.WATCH,
                f"Örüntü örneklem içinde çoklu test sonrası anlamlı {_cite(_ids(ins))} ve örneklem "
                f"dışında aynı yönde sürdü {_cite(_ids(stab))}; yine de işlem kuralı değildir.",
                _ids(ins) + _ids(stab),
                "s2_watch",
            )
        return Decision(
            A.REJECT_SIGNAL,
            f"Haftanın günü örüntüsü istatistiksel olarak kararlı değil: çoklu test "
            f"düzeltmesi sonrası örneklem içi kanıt zayıf {_cite(_ids(ins))} ve örneklem dışı sonuç "
            f"yetersiz ya da ters yönde {_cite(_ids(stab))}.",
            _ids(ins) + _ids(stab),
            "s2_reject",
        )
    if sc is Scenario.S1_SECTOR_CATCH_UP:
        strength = _find(c, "sector.*.strength.w*")
        lag = [x for x in _find(c, "sector.*.lag.w*") if x["values"].get("laggard")]
        persistent = _find(c, "sector.*.persistent_lag")
        catch = sorted(_find(c, "sector.*.catch_up.h*"), key=lambda x: int(x["key"].rsplit("h", 1)[1]))
        bt = _find(c, "backtest.B_TECH_SECTOR")
        if not lag:
            return Decision(
                A.HOLD,
                f"Güçlü bir sektörde belirgin biçimde geride kalan hisse yok {_cite(_ids(strength))}.",
                _ids(strength),
                "s1_no_laggard",
            )
        if persistent:
            return Decision(
                A.INVESTIGATE,
                f"Geride kalma uzun pencerelerde de sürüyor {_cite(_ids(persistent))}; "
                f"yapısal mı geçici mi olduğu temel/makro kanıtla ayrıştırılmalı.",
                _ids(lag) + _ids(persistent),
                "s1_structural",
            )
        last = catch[-1]["values"] if catch else {}
        edge = (last.get("hit_rate") or 0) - (last.get("baseline_hit_rate") or 1)
        if (
            catch
            and (last.get("n") or 0) >= r["min_events"]
            and edge >= r["min_hit_rate_edge"]
            and bt
            and (bt[0]["values"].get("vs_xu100") or 0) > 0
        ):
            return Decision(
                A.POTENTIAL_CATCH_UP_CANDIDATE,
                f"Hisse güçlü sektöründe geride {_cite(_ids(lag))}; geçmişte "
                f"geride kalma girişleri akranları geçme eğiliminde {_cite(_ids(catch[-1:]))} ve sektör "
                f"stratejisi testi XU100'ün üzerinde {_cite(_ids(bt))}.",
                _ids(lag) + _ids(catch[-1:]) + _ids(bt),
                "s1_candidate",
            )
        return Decision(
            A.WATCH,
            f"Hisse güçlü sektöründe geride {_cite(_ids(lag))}, ancak geçmişte geride kalanların "
            f"akranlarını yakalama oranı geride kalmayan günlerden belirgin biçimde yüksek değil "
            f"{_cite(_ids(catch))} ya da strateji testi desteklemiyor {_cite(_ids(bt))}.",
            _ids(lag) + _ids(catch) + _ids(bt),
            "s1_watch",
        )
    # S4
    margin = _find(c, f"fundamental_change.{t}.*.ebitda_margin")
    ni = _find(c, f"fundamentals.{t}.net_income_parent.yoy_ytd")
    agg = _find(c, f"fundamental_change.{t}.aggregate.h*")
    bt = _find(c, "backtest.C_TECH_SECTOR_FUND")
    improving = (bool(margin) and (margin[0]["values"].get("change") or 0) > 0) or (
        not margin and bool(ni) and (ni[0]["values"].get("yoy") or 0) > 0
    )
    reaction_ok = (
        bool(agg) and (agg[0]["values"].get("mean_abn_xu100") or 0) > 0 and (agg[0]["values"].get("n") or 0) >= 5
    )
    bt_ok = bool(bt) and (bt[0]["values"].get("vs_xu100") or 0) > 0
    if improving and reaction_ok and bt_ok:
        return Decision(
            A.FUNDAMENTAL_IMPROVEMENT_CANDIDATE,
            f"Son raporda iyileşme var {_cite(_ids(margin or ni))}; "
            f"geçmiş açıklamaların ardından ortalama anormal getiri pozitif {_cite(_ids(agg))} ve temel "
            f"filtreli strateji testi XU100'ün üzerinde {_cite(_ids(bt))}.",
            _ids(margin or ni) + _ids(agg) + _ids(bt),
            "s4_candidate",
        )
    if improving:
        return Decision(
            A.WATCH,
            f"Son raporda iyileşme var {_cite(_ids(margin or ni))}, ancak geçmiş fiyat tepkisi ya da "
            f"strateji testi bunu desteklemiyor {_cite(_ids(agg) + _ids(bt))}.",
            _ids(margin or ni) + _ids(agg) + _ids(bt),
            "s4_watch",
        )
    return Decision(
        A.HOLD,
        f"Son raporda belirgin bir iyileşme görülmüyor {_cite(_ids(margin or ni))}.",
        _ids(margin or ni),
        "s4_hold",
    )
