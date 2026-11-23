"""Question understanding by the local LLM: free Turkish question -> structured AnalysisRequest (validated).

Used when the deterministic keyword parser cannot place a question (unexpected wording, company names instead of
codes) and as a fine-tuning skill. The output is constrained by a JSON schema whose ticker enum is the universe, and
then validated again; anything invalid falls back to "out of scope" instead of guessing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bistharness.core.config import Universe, read_config_yaml
from bistharness.core.enums import Scenario
from bistharness.harness.llm_client import LLMClient
from bistharness.harness.request import ADVICE_RE, AnalysisRequest, QuestionParseError, parse_question
from bistharness.tools.weekday_tool import SEQUENCE_PRESETS, WEEKDAY_PRESETS

INTENT_SYSTEM = """Sen bir BIST analiz sisteminin soru anlama modülüsün. Kullanıcının sorusunu yapılandırılmış bir analiz
isteğine çevirirsin; analiz yapmaz, sayı yazmaz, yorum yapmazsın.
Senaryolar:
- S1_SECTOR_CATCH_UP: sektörde/akranlara göre geride kalan, lider, yakalama (catch-up) soruları (2+ hisse ya da bir sektör)
- S2_WEEKDAY_PATTERN: haftanın günü / art arda günler örüntüsü soruları
- S3_TECHNICAL_REVERSAL: Bollinger, RSI, Supertrend, KAMA, Ichimoku, destek/direnç, teknik dönüş soruları
- S4_FUNDAMENTAL_REACTION: bilanço, FAVÖK, marj, kârlılık, KAP açıklaması sonrası fiyat tepkisi soruları
- SAFETY_ADVICE_REQUEST: al/sat, hedef fiyat, stop, "kesin yükselir mi", "kazanır mıyım" gibi tavsiye/tahmin talepleri
Kurallar: tickers yalnızca listedeki BIST kodlarıdır (şirket adını koda çevir). Tavsiye/hedef fiyat/tahmin isteniyorsa
advice_requested=true ve scenario=SAFETY_ADVICE_REQUEST. Evren dışı varlık (kripto, yabancı hisse, emtia), gelecek
fiyat tahmini ya da finans dışı istek ise in_scope=false, scenario=null ve reason_tr'de kısa gerekçe."""


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_scope: bool
    scenario: Scenario | None = None
    tickers: list[str] = Field(default_factory=list)
    advice_requested: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    reason_tr: str = ""


def intent_schema(universe: Universe) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "in_scope": {"type": "boolean"},
            "scenario": {"type": ["string", "null"], "enum": [s.value for s in Scenario] + [None]},
            # maxItems / maxLength bound the constrained decoding: greedy decoding once looped "KATMR, KATMR, ..."
            # for 83 s on an out-of-universe name (the largest peer group has 10 members)
            "tickers": {
                "type": "array",
                "items": {"type": "string", "enum": list(universe.all_stock_tickers())},
                "maxItems": 10,
            },
            "advice_requested": {"type": "boolean"},
            "params": {"type": "object"},
            "reason_tr": {"type": "string", "maxLength": 300},
        },
        "required": ["in_scope", "scenario", "tickers", "advice_requested", "params", "reason_tr"],
    }


def intent_messages(question: str, as_of: date) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": INTENT_SYSTEM},
        {"role": "user", "content": f"Analiz tarihi: {as_of.isoformat()}\nSoru: {question}"},
    ]


def check_intent(raw: str | dict[str, Any], universe: Universe) -> tuple[Intent | None, list[str]]:
    try:
        it = Intent.model_validate(json.loads(raw) if isinstance(raw, str) else raw)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        return None, [f"schema: {str(exc).splitlines()[0][:200]}"]
    it = it.model_copy(update={"tickers": list(dict.fromkeys(it.tickers))})  # ["TCELL", "TCELL"] -> ["TCELL"]
    errors = []
    known = set(universe.all_stock_tickers())
    bad = [t for t in it.tickers if t not in known]
    if bad:
        errors.append(f"unknown tickers {bad}")
    if it.in_scope and (it.scenario is None or not it.tickers):
        errors.append("an in-scope request needs a scenario and at least one ticker")
    if it.advice_requested and it.in_scope and it.scenario is not Scenario.SAFETY_ADVICE_REQUEST:
        errors.append("an advice request must use SAFETY_ADVICE_REQUEST")
    if (
        it.scenario is Scenario.S1_SECTOR_CATCH_UP
        and len(it.tickers) == 1
        and universe.instrument(it.tickers[0]).peer_group is None
    ):
        errors.append("S1 needs a peer group")
    return (it if not errors else None), errors


def intent_of_request(req: AnalysisRequest) -> Intent:
    """Teacher target for a structured request."""
    return Intent(
        in_scope=True,
        scenario=req.scenario,
        tickers=list(req.tickers),
        advice_requested=req.advice_requested,
        params=dict(req.params),
        reason_tr="",
    )


def to_request(it: Intent, question: str, as_of: date) -> AnalysisRequest | None:
    if not it.in_scope or it.scenario is None or not it.tickers:
        return None
    return AnalysisRequest(
        question=question,
        scenario=it.scenario,
        tickers=it.tickers,
        as_of_date=as_of,
        params=it.params,
        advice_requested=it.advice_requested,
    )


def parse_with_llm(
    question: str, *, as_of: date, universe: Universe, client: LLMClient
) -> tuple[Intent | None, list[str]]:
    resp = client.chat(intent_messages(question, as_of), intent_schema(universe))
    return check_intent(resp.text, universe)


# ------------------------------------------------------------------------------------- question -> request
UNDERSTAND_MODES = ("rules", "llm", "hybrid")
_DATE_PARAMS = ("in_sample_start", "in_sample_end", "out_of_sample_start")


def clean_params(scenario: Scenario, params: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Keeps only parameters the planner understands, with valid values; everything else is dropped (and reported)."""
    out: dict[str, Any] = {}
    dropped: list[str] = []
    for key, val in params.items():
        ok = False
        if key == "pattern" and scenario is Scenario.S2_WEEKDAY_PATTERN:
            ok = isinstance(val, str) and (val in WEEKDAY_PRESETS or val in SEQUENCE_PRESETS)
        elif key == "horizon" and scenario is Scenario.S1_SECTOR_CATCH_UP:
            ok = isinstance(val, int) and not isinstance(val, bool) and 1 <= val <= 250
        elif key in _DATE_PARAMS and scenario is Scenario.S2_WEEKDAY_PATTERN:
            try:
                date.fromisoformat(str(val))
                ok = True
            except ValueError:
                ok = False
        elif key == "tx_cost_bps" and scenario is Scenario.S2_WEEKDAY_PATTERN:
            ok = isinstance(val, int | float) and not isinstance(val, bool) and 0 <= val <= 500
        if ok:
            out[key] = val
        else:
            dropped.append(key)
    return out, dropped


# ------------------------------------------------------------------- ticker grounding (config/ticker_aliases.yaml)
_FOLD = str.maketrans("ıİğĞüÜşŞöÖçÇâÂîÎûÛ", "iIgGuUsSoOcCaAiIuU")


def fold(text: str) -> str:
    """Turkish-folded lower case: 'Ereğli' and 'eregli' compare equal; length-preserving."""
    return text.translate(_FOLD).lower()


@dataclass(frozen=True)
class Aliases:
    tickers: dict[str, tuple[str, ...]]
    groups: dict[str, tuple[str, ...]]
    lowercase_code_excluded: frozenset[str]


@lru_cache(maxsize=1)
def load_aliases() -> Aliases:
    raw = read_config_yaml("ticker_aliases.yaml")
    return Aliases(
        {t: tuple(fold(a) for a in al) for t, al in raw["tickers"].items()},
        {g: tuple(fold(a) for a in al) for g, al in raw["groups"].items()},
        frozenset(raw.get("lowercase_code_excluded", [])),
    )


def _alias_re(alias: str) -> re.Pattern[str]:
    a = re.escape(alias)
    if len(alias) <= 4:  # short aliases are whole tokens (THY'de ok, "tavan" is not TAV)
        return re.compile(rf"(?<![a-z0-9]){a}(?:'[a-z]*)?(?![a-z0-9])")
    return re.compile(rf"(?<![a-z0-9]){a}")  # long aliases may carry a Turkish suffix (aselsanın)


def _find(text: str, aliases: list[tuple[str, str]]) -> tuple[list[tuple[int, str]], str]:
    """(position, key) hits, longest alias first; matched spans are blanked so 'aksa enerji' hides 'aksa'."""
    hits: list[tuple[int, str]] = []
    for alias, key in sorted(aliases, key=lambda x: -len(x[0])):
        for m in list(_alias_re(alias).finditer(text)):
            hits.append((m.start(), key))
            text = text[: m.start()] + " " * (m.end() - m.start()) + text[m.end() :]
    return hits, text


def mentioned_tickers(question: str, universe: Universe, aliases: Aliases | None = None) -> list[str]:
    """Universe tickers named in the question (company name or code), in order of appearance."""
    al = aliases or load_aliases()
    known = set(universe.all_stock_tickers())
    text = fold(question)
    hits, rest = _find(text, [(a, t) for t, names in al.tickers.items() if t in known for a in names])
    same_len = len(text) == len(question)
    for m in re.finditer(r"(?<![a-z0-9])([a-z]{4,6})(?![a-z0-9])", rest):
        code = m.group(1).upper()
        if code not in known:
            continue
        written = question[m.start() : m.end()] if same_len else m.group(1)
        if written.isupper() or code not in al.lowercase_code_excluded:
            hits.append((m.start(), code))
    return list(dict.fromkeys(t for _, t in sorted(hits)))


def mentioned_groups(question: str, aliases: Aliases | None = None) -> set[str]:
    al = aliases or load_aliases()
    hits, _ = _find(fold(question), [(a, g) for g, words in al.groups.items() for a in words])
    return {g for _, g in hits}


def ground_tickers(question: str, scenario: Scenario, proposed: list[str], universe: Universe) -> tuple[list[str], str]:
    """Reconciles the model's tickers with what the question actually names.

    Named tickers win (a wrong name -> code mapping is dropped, an omitted code is added); in a sector question the
    model may add peers of a named ticker or members of a named sector. Returns (tickers, source) where source is
    'question', 'sector' or '' (nothing grounded: the system declines rather than guess)."""
    named = mentioned_tickers(question, universe)
    groups = mentioned_groups(question)

    def group(t: str) -> str | None:
        return universe.instrument(t).peer_group

    if named:
        allowed = {group(t) for t in named} | groups
        extra = [
            t for t in proposed if t not in named and scenario is Scenario.S1_SECTOR_CATCH_UP and group(t) in allowed
        ]
        return named + extra, "question"
    in_sector = [t for t in proposed if group(t) in groups]
    return in_sector, ("sector" if in_sector else "")


@dataclass(frozen=True)
class Understanding:
    """How a free-text question was understood. `request` is None when the system declines to analyse it."""

    request: AnalysisRequest | None
    method: str  # rules | llm | none
    intent: Intent | None = None
    errors: tuple[str, ...] = ()
    message_tr: str = ""  # why it is not analysed (shown to the user)
    advice_override: bool = False  # the advice regex forced SAFETY_ADVICE_REQUEST over the model's choice
    dropped_params: tuple[str, ...] = ()
    ticker_source: str = ""  # question | sector | rules
    tickers_added: tuple[str, ...] = ()  # named in the question but missing from the model's answer
    tickers_dropped: tuple[str, ...] = ()  # proposed by the model but not named in the question


def _rules(question: str, as_of: date, universe: Universe, errors: tuple[str, ...] = ()) -> Understanding:
    try:
        return Understanding(parse_question(question, as_of=as_of, universe=universe), "rules", ticker_source="rules")
    except QuestionParseError as exc:
        return Understanding(None, "none", errors=(*errors, str(exc)), message_tr=str(exc))


def understand_question(
    question: str,
    *,
    as_of: date,
    universe: Universe,
    client: LLMClient | None = None,
    mode: str = "llm",
) -> Understanding:
    """rules: keyword parser only. llm: the local model, the keyword parser if the model fails or is unavailable.
    hybrid: keyword parser first, the model only when it fails (kept for the comparison in eval/robustness.py).

    The model only PROPOSES; deterministic checks decide (CLAUDE.md core principle): tickers are grounded in the
    question (ground_tickers), an explicit advice phrase (ADVICE_RE) always routes to the safety scenario, and model
    parameters are reduced to known keys with valid values."""
    if mode not in UNDERSTAND_MODES:
        raise ValueError(f"mode must be one of {UNDERSTAND_MODES}")
    if mode == "rules" or client is None:
        return _rules(question, as_of, universe)
    if mode == "hybrid":
        first = _rules(question, as_of, universe)
        if first.request is not None:
            return first
    try:
        it, errs = parse_with_llm(question, as_of=as_of, universe=universe, client=client)
    except Exception as exc:  # local model unavailable (Ollama down, timeout): keyword parser instead
        return _rules(question, as_of, universe, (f"llm unavailable: {exc}",))
    if it is None:
        fb = _rules(question, as_of, universe, tuple(errs))
        if fb.request is not None:
            return fb
        msg = "soru anlaşılamadı; hisse kodunu ve konuyu (sektör, haftanın günü, teknik dönüş, bilanço) belirtin"
        return Understanding(None, "none", errors=fb.errors, message_tr=msg)
    if not it.in_scope:
        return Understanding(None, "llm", it, message_tr=it.reason_tr or "soru analiz kapsamı dışında")
    override = bool(ADVICE_RE.search(question)) and it.scenario is not Scenario.SAFETY_ADVICE_REQUEST
    if override:
        it = it.model_copy(update={"scenario": Scenario.SAFETY_ADVICE_REQUEST, "advice_requested": True})
    assert it.scenario is not None  # check_intent guarantees a scenario for in-scope intents
    tickers, source = ground_tickers(question, it.scenario, it.tickers, universe)
    added = tuple(t for t in tickers if t not in it.tickers)
    dropped_t = tuple(t for t in it.tickers if t not in tickers)
    if not tickers:
        msg = (
            "sorudaki hisse analiz evreninde bulunamadı (örn. ASELS, Tüpraş); evrendeki bir hisse kodu ya da "
            "şirket adı yazın"
        )
        return Understanding(None, "llm", it, message_tr=msg, advice_override=override, tickers_dropped=dropped_t)
    params, dropped = clean_params(it.scenario, it.params)
    it = it.model_copy(update={"params": params, "tickers": tickers})
    if (
        it.scenario is Scenario.S1_SECTOR_CATCH_UP
        and len(tickers) == 1
        and universe.instrument(tickers[0]).peer_group is None
    ):
        return Understanding(None, "llm", it, message_tr="sektör karşılaştırması için akran grubu yok")
    return Understanding(
        to_request(it, question, as_of),
        "llm",
        it,
        advice_override=override,
        dropped_params=tuple(dropped),
        ticker_source=source,
        tickers_added=added,
        tickers_dropped=dropped_t,
    )
