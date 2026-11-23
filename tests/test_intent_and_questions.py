"""LLM question understanding (validated intent) and the dataset question bank."""

from __future__ import annotations

import json
import random
from datetime import date

from bistharness.core.config import load_universe
from bistharness.core.enums import Scenario
from bistharness.harness.intent import check_intent, intent_of_request, intent_schema, parse_with_llm, to_request
from bistharness.harness.llm_client import ScriptedClient
from bistharness.harness.request import AnalysisRequest
from training.question_bank import company_names, make_question, out_of_scope

U = load_universe()
AS_OF = date(2026, 9, 10)


def test_valid_and_invalid_intents() -> None:
    ok, err = check_intent(
        {
            "in_scope": True,
            "scenario": "S3_TECHNICAL_REVERSAL",
            "tickers": ["ASELS"],
            "advice_requested": False,
            "params": {},
            "reason_tr": "",
        },
        U,
    )
    assert ok is not None and not err
    req = to_request(ok, "soru", AS_OF)
    assert req is not None and req.tickers == ["ASELS"]
    _, err = check_intent(
        {
            "in_scope": True,
            "scenario": "S3_TECHNICAL_REVERSAL",
            "tickers": ["AAPL"],
            "advice_requested": False,
            "params": {},
            "reason_tr": "",
        },
        U,
    )
    assert any("unknown tickers" in e for e in err)
    _, err = check_intent(
        {
            "in_scope": True,
            "scenario": "S3_TECHNICAL_REVERSAL",
            "tickers": ["ASELS"],
            "advice_requested": True,
            "params": {},
            "reason_tr": "",
        },
        U,
    )
    assert any("SAFETY_ADVICE_REQUEST" in e for e in err)
    oos, err = check_intent(
        {
            "in_scope": False,
            "scenario": None,
            "tickers": [],
            "advice_requested": False,
            "params": {},
            "reason_tr": "kripto evren dışı",
        },
        U,
    )
    assert oos is not None and to_request(oos, "x", AS_OF) is None
    assert check_intent("{bozuk", U)[0] is None


def test_llm_parse_uses_the_universe_enum_and_round_trips_a_request() -> None:
    req = AnalysisRequest(question="q", scenario=Scenario.S4_FUNDAMENTAL_REACTION, tickers=["TUPRS"], as_of_date=AS_OF)
    target = intent_of_request(req).model_dump(mode="json")
    client = ScriptedClient([json.dumps(target)])
    it, err = parse_with_llm("Tüpraş bilançosu sonrası ne oldu?", as_of=AS_OF, universe=U, client=client)
    assert it is not None and not err and it.tickers == ["TUPRS"]
    schema = intent_schema(U)
    assert "TUPRS" in schema["properties"]["tickers"]["items"]["enum"]


def test_question_bank_is_deterministic_and_varied() -> None:
    names = company_names()
    a = [make_question(Scenario.S3_TECHNICAL_REVERSAL, ["THYAO"], random.Random(1), names, U).text for _ in range(1)]
    b = [make_question(Scenario.S3_TECHNICAL_REVERSAL, ["THYAO"], random.Random(1), names, U).text for _ in range(1)]
    assert a == b
    rng = random.Random(7)
    texts = {make_question(Scenario.S4_FUNDAMENTAL_REACTION, ["TUPRS"], rng, names, U).text for _ in range(60)}
    assert len(texts) > 15
    assert any("Tüpraş" in t or "Tupras" in t or "tüpraş" in t or "tupras" in t for t in texts)  # company names too
    q = make_question(Scenario.SAFETY_ADVICE_REQUEST, ["EREGL"], rng, names, U)
    assert q.advice and q.scenario is Scenario.SAFETY_ADVICE_REQUEST
    o = out_of_scope(rng)
    assert not o.in_scope and o.reason


# ------------------------------------------------------------------------------ understand_question (free text)
def _intent(**kw: object) -> str:
    base: dict[str, object] = {
        "in_scope": True,
        "scenario": "S3_TECHNICAL_REVERSAL",
        "tickers": ["ASELS"],
        "advice_requested": False,
        "params": {},
        "reason_tr": "",
    }
    return json.dumps({**base, **kw})


def test_advice_regex_needs_a_word_boundary() -> None:
    from bistharness.harness.request import ADVICE_RE

    assert not ADVICE_RE.search("Bu düşüş normal mi?")
    assert not ADVICE_RE.search("genel mi bakalım")
    assert ADVICE_RE.search("ASELS al mı?") and ADVICE_RE.search("THYAO alayım mı")


def test_hybrid_uses_rules_first_and_the_model_only_as_fallback() -> None:
    from bistharness.harness.intent import understand_question

    u = load_universe()
    client = ScriptedClient(responses=[_intent(tickers=["EREGL"])])
    ok = understand_question("ASELS'te Bollinger alt bandı?", as_of=AS_OF, universe=u, client=client, mode="hybrid")
    assert ok.method == "rules" and ok.request is not None and client.calls == []
    fb = understand_question("Erdemir alt banda değince?", as_of=AS_OF, universe=u, client=client, mode="hybrid")
    assert fb.method == "llm" and fb.request is not None and fb.request.tickers == ["EREGL"]
    none = understand_question("Erdemir alt banda değince?", as_of=AS_OF, universe=u, mode="rules")
    assert none.request is None and none.message_tr


def test_model_path_forces_safety_on_explicit_advice_and_cleans_params() -> None:
    from bistharness.harness.intent import understand_question

    u = load_universe()
    advice = ScriptedClient(responses=[_intent()])  # the model missed the advice part
    a = understand_question("ASELS alt banda değdi, alayım mı?", as_of=AS_OF, universe=u, client=advice, mode="llm")
    assert a.advice_override and a.request is not None
    assert a.request.scenario is Scenario.SAFETY_ADVICE_REQUEST and a.request.advice_requested
    s2 = _intent(scenario="S2_WEEKDAY_PATTERN", params={"pattern": "MON_DOWN__FRI", "bogus": 1, "tx_cost_bps": "x"})
    q = "ASELS pazartesi düşerse cuma?"
    p = understand_question(q, as_of=AS_OF, universe=u, client=ScriptedClient(responses=[s2]), mode="llm")
    assert p.request is not None and p.request.params == {"pattern": "MON_DOWN__FRI"}
    assert set(p.dropped_params) == {"bogus", "tx_cost_bps"}
    bad_pattern = _intent(scenario="S2_WEEKDAY_PATTERN", params={"pattern": "FULL_MOON"})
    b = understand_question(q, as_of=AS_OF, universe=u, client=ScriptedClient(responses=[bad_pattern]), mode="llm")
    assert b.request is not None and b.request.params == {}


def test_model_path_declines_out_of_scope_and_invalid_answers() -> None:
    from bistharness.harness.intent import understand_question

    u = load_universe()
    oos = _intent(in_scope=False, scenario=None, tickers=[], reason_tr="kripto evrende değil")
    o = understand_question("Bitcoin?", as_of=AS_OF, universe=u, client=ScriptedClient(responses=[oos]), mode="llm")
    assert o.request is None and o.message_tr == "kripto evrende değil"
    junk = understand_question("x", as_of=AS_OF, universe=u, client=ScriptedClient(responses=["not json"]), mode="llm")
    assert junk.request is None and junk.method == "none" and junk.errors
    # an invalid model answer falls back to the keyword parser when that can place the question
    fb = understand_question(
        "ASELS Bollinger?", as_of=AS_OF, universe=u, client=ScriptedClient(responses=["not json"]), mode="llm"
    )
    assert fb.method == "rules" and fb.request is not None


def test_robustness_scoring() -> None:
    from bistharness.harness.intent import Understanding
    from eval.robustness import load_questions, score

    u = load_universe()
    assert len(load_questions()) == 50
    req = AnalysisRequest(
        question="q", scenario=Scenario.S1_SECTOR_CATCH_UP, tickers=["GARAN", "AKBNK"], as_of_date=AS_OF
    )
    group = {"scenario": "S1_SECTOR_CATCH_UP", "group": "Bankacilik", "tickers_must": ["GARAN"]}
    assert score(Understanding(req, "llm"), group, u)["outcome"] == "correct"
    assert score(Understanding(None, "none"), group, u)["outcome"] == "declined"
    advice = {"scenario": "SAFETY_ADVICE_REQUEST", "tickers": ["GARAN"], "accept": ["OUT"]}
    assert score(Understanding(req, "llm"), advice, u)["outcome"] == "advice_not_caught"
    assert score(Understanding(None, "llm"), advice, u)["outcome"] == "correct"
    assert score(Understanding(req, "llm"), {"scenario": "OUT"}, u)["outcome"] == "analysed_out_of_scope"
    safety = AnalysisRequest(question="q", scenario=Scenario.SAFETY_ADVICE_REQUEST, tickers=["GARAN"], as_of_date=AS_OF)
    alt = {"scenario": "OUT", "accept": ["SAFETY_ADVICE_REQUEST"]}  # R50: no tickers in the expectation
    assert score(Understanding(safety, "llm"), alt, u)["outcome"] == "correct"


def test_advice_regex_catches_forward_looking_requests_but_not_history() -> None:
    from bistharness.harness.request import ADVICE_RE

    for q in [
        "Hangi banka hissesi en çok kazandırır?",
        "EREGL'e 100 bin TL yatırsam?",
        "THYAO için alım fırsatı mı?",
        "KCHOL alınır mı satılır mı?",
        "TUPRS'te stop nereye?",
        "Pegasus yarın tavan olur mu?",
    ]:
        assert ADVICE_RE.search(q), q
    for q in ["Bu sinyal geçmişte kazandırmış mı?", "En çok kazandıran sektör hangisiydi?", "satış baskısı var mı"]:
        assert not ADVICE_RE.search(q), q


def test_ticker_grounding_names_codes_and_sectors() -> None:
    from bistharness.harness.intent import fold, ground_tickers, mentioned_groups, mentioned_tickers

    u = load_universe()
    assert fold("Ereğli İSDEMİR Şişecam") == "eregli isdemir sisecam"
    assert mentioned_tickers("eregli, kardemir ve isdemir", u) == ["EREGL", "KRDMD", "ISDMR"]
    assert mentioned_tickers("Aksa Enerji ve Aksa Akrilik", u) == ["AKSEN", "AKSA"]  # longest alias first
    assert mentioned_tickers("THY'de ne oldu", u) == ["THYAO"]
    assert mentioned_tickers("Pegasus yarın tavan olur mu?", u) == ["PGSUS"]  # "tavan" is not TAV
    assert mentioned_tickers("hedef fiyat garanti mi", u) == []  # "garanti" alone is not the bank
    assert mentioned_tickers("mavi bant ve logo", u) == []  # everyday words, not lower-case codes
    assert mentioned_tickers("MAVI ve sasa", u) == ["MAVI", "SASA"]
    assert mentioned_groups("çimentocular ve bankaların") == {"Insaat_Yapi_Malzemeleri", "Bankacilik"}
    s1 = Scenario.S1_SECTOR_CATCH_UP
    # wrong name -> code mapping is dropped, the named company is used
    assert ground_tickers("Migros ile Şok Marketler", s1, ["MIATK", "SOKM"], u) == (["MGROS", "SOKM"], "question")
    # an omitted code is added
    assert ground_tickers("KCHOL SAHOL ALARK sıralaması", s1, ["KCHOL", "SAHOL"], u)[0] == ["KCHOL", "SAHOL", "ALARK"]
    # sector question: model members of the named sector are kept, others are not
    assert ground_tickers("Bankalar arasında geride kalan?", s1, ["GARAN", "AKBNK", "TUPRS"], u) == (
        ["GARAN", "AKBNK"],
        "sector",
    )
    # nothing named: the model's guess is not used
    assert ground_tickers("Kontrolmatik (KONTR) geride mi?", s1, ["KORDS"], u) == ([], "")


def test_understanding_declines_ungrounded_tickers_and_reports_corrections() -> None:
    from bistharness.harness.intent import understand_question

    u = load_universe()
    guess = ScriptedClient(responses=[_intent(scenario="S1_SECTOR_CATCH_UP", tickers=["KORDS", "AKSA"])])
    d = understand_question("Kontrolmatik (KONTR) geride mi?", as_of=AS_OF, universe=u, client=guess, mode="llm")
    assert d.request is None and d.tickers_dropped == ("KORDS", "AKSA") and "evreninde" in d.message_tr
    fix = ScriptedClient(responses=[_intent(tickers=["SELEC"])])
    f = understand_question("Şişecam'da alt bant?", as_of=AS_OF, universe=u, client=fix, mode="llm")
    assert f.request is not None and f.request.tickers == ["SISE"]
    assert f.tickers_added == ("SISE",) and f.tickers_dropped == ("SELEC",) and f.ticker_source == "question"


def test_intent_schema_bounds_lists_and_duplicates_collapse() -> None:
    u = load_universe()
    schema = intent_schema(u)
    assert schema["properties"]["tickers"]["maxItems"] == 10
    it, errs = check_intent(
        json.dumps(
            {
                "in_scope": True,
                "scenario": "S3_TECHNICAL_REVERSAL",
                "tickers": ["TCELL", "TCELL"],
                "advice_requested": False,
                "params": {},
                "reason_tr": "",
            }
        ),
        u,
    )
    assert it is not None and it.tickers == ["TCELL"] and errs == []
