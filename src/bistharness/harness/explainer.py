"""GENERATE_EXPLANATION: the LLM (or the deterministic template) turns the committed evidence into an educational
analytical state. Only the Committed Evidence Set (E1..En with display values), the gate and the allowed actions
are shown to the model. Output = JSON (LLMOutput); validator; one corrective retry; then the deterministic
ANALYSIS_UNSAFE template. The harness adds the fixed refusal template (advice requests) and the disclaimer.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from bistharness.core.enums import ALLOWED_ACTIONS_BY_GATE, AnalyticalAction, GateStatus
from bistharness.harness.decision import decide
from bistharness.harness.llm_client import LLMClient
from bistharness.harness.policy import Policy
from bistharness.harness.request import AnalysisRequest
from bistharness.harness.validator import ValidationResult, output_schema, validate

SYSTEM_PROMPT = """Sen BIST hisseleri için EĞİTSEL bir analiz asistanısın. Görevin, sana verilen ve deterministik
Python araçlarıyla hesaplanmış kanıtları (E1, E2, ...) Türkçe olarak açıklamak ve izinli eylemlerden birini seçmektir.

Kurallar (ihlal edilirse cevabın reddedilir):
1. Yalnızca verilen kanıtları kullan. Açıklamadaki HER sayı, bir kanıtta yazdığı biçimle BİREBİR aynı olmalıdır
   (ör. "%66,67", "1.234,50", "4,63 puan"). Hesap yapma, yuvarlama, yeni sayı üretme. Birimi koru: yüzdeleri %
   işaretiyle, adetleri (olay/işlem sayısı) yüzde işareti OLMADAN, puan farklarını "puan" ile yaz.
   Sayıların yönünü doğru oku: -1,26 değeri -1,15'ten KÜÇÜKTÜR; %82,35 oranı %73,53'ten BÜYÜKTÜR.
2. Her iddianın sonunda dayandığı kanıtı parantez içinde belirt: (E3). cited_evidence listesine de yaz.
3. Yatırım tavsiyesi verme: al/sat önerisi, hedef fiyat, stop seviyesi, "kesin", "garanti" gibi ifadeler YASAK.
   Soru tavsiye/hedef fiyat istiyorsa refusal_needed=true yap; ret cümlesini sistem ekler, sen yazma.
4. action alanı yalnızca verilen izinli eylemlerden biri olabilir. *_CANDIDATE eylemleri bir backtest kanıtına
   atıf gerektirir. Kanıt zayıfsa, örneklem küçükse ya da çoklu test sonrası anlamlılık yoksa temkinli eylem seç.
5. Geçmiş sonuçlar geleceği garanti etmez; korelasyon nedensellik değildir. Sınırlamaları limitations_tr alanına yaz.
6. Yalnızca istenen JSON nesnesini döndür."""

ACTION_GUIDE = {
    "HOLD": "durumda belirgin değişiklik yok",
    "WATCH": "izlenmeye değer ama kanıt bir aday etiketi için yeterli değil",
    "INVESTIGATE": "kanıt eksik/çelişkili ya da örneklem küçük; daha fazla inceleme gerekir",
    "POTENTIAL_CATCH_UP_CANDIDATE": "güçlü sektörde geride kalan ve tarihsel/backtest kanıtı yakalamayı destekleyen hisse",
    "TECHNICAL_REVERSAL_CANDIDATE": "güncel teknik dönüş olayı tarihsel ve backtest kanıtıyla destekleniyor",
    "FUNDAMENTAL_IMPROVEMENT_CANDIDATE": "temel iyileşme tarihsel tepki ve backtest kanıtıyla destekleniyor",
    "REJECT_SIGNAL": "incelenen sinyal/örüntü tarihsel kanıtla desteklenmiyor",
    "ANALYSIS_UNSAFE": "veri/kanıt güvenilir bir sonuç için uygun değil",
}


@dataclass
class Attempt:
    raw: str
    validation: ValidationResult
    prompt_hash: str = ""
    model: str = ""
    digest: str = ""
    seconds: float = 0.0
    messages: list[dict[str, str]] = field(default_factory=list)


@dataclass
class Explanation:
    action: AnalyticalAction
    text_tr: str  # final text shown to the user (refusal template + explanation + limitations + disclaimer)
    cited: list[str]
    attempts: list[Attempt]
    fallback_used: bool
    explainer: str
    teacher_action: AnalyticalAction | None = None
    teacher_rule: str | None = None


class Explainer(Protocol):
    name: str

    def explain(self, req: AnalysisRequest, bundle: dict[str, Any], gate: GateStatus) -> Explanation: ...


def evidence_block(committed: Sequence[dict[str, Any]]) -> str:
    return "\n".join(f"{c['id']}: {c['claim_tr']}" for c in committed)


def user_prompt(req: AnalysisRequest, bundle: dict[str, Any], gate: GateStatus) -> str:
    allowed = sorted(a.value for a in ALLOWED_ACTIONS_BY_GATE[gate])
    guide = "\n".join(f"- {a}: {ACTION_GUIDE[a]}" for a in allowed)
    return (
        f"Soru: {req.question}\nSenaryo: {req.scenario.value}\nHisse(ler): {', '.join(req.tickers)}\n"
        f"Analiz tarihi (as_of): {req.as_of_date.isoformat()}\nRisk ve veri kalitesi kapısı: {gate.value}\n"
        f"İzinli eylemler:\n{guide}\n\nKanıtlar (yalnızca bunları kullan, sayıları birebir kopyala):\n"
        f"{evidence_block(bundle['committed'])}\n\n"
        "JSON alanları: action, explanation_tr (3-6 cümle, her iddia (E#) ile), cited_evidence (E# listesi), "
        "refusal_needed (tavsiye/hedef fiyat istendiyse true), limitations_tr (1-2 cümle sınırlama)."
    )


def feedback_prompt(v: ValidationResult) -> str:
    return (
        "Cevabın denetimden geçmedi. Hatalar:\n- "
        + "\n- ".join(v.errors)
        + "\nYalnızca kanıtlardaki sayıları birebir kullanarak ve kurallara uyarak JSON'u yeniden üret."
    )


def _validate(
    raw: str | dict[str, Any], req: AnalysisRequest, bundle: dict[str, Any], gate: GateStatus, policy: Policy
) -> ValidationResult:
    return validate(
        raw,
        committed=bundle["committed"],
        allowed_numbers=bundle["allowed_numbers"],
        allowed_dates=bundle["allowed_dates"],
        gate=gate,
        rules=policy.validation,
        as_of=req.as_of_date,
        advice_requested=req.advice_requested,
    )


def finalize_text(policy: Policy, explanation: str, limitations: str, refusal: bool) -> str:
    parts = [policy.validation.refusal_template] if refusal else []
    parts.append(explanation.strip())
    if limitations.strip():
        parts.append(limitations.strip())
    parts.append(policy.validation.disclaimer)
    return "\n\n".join(parts)


def unsafe(policy: Policy, reason: str, attempts: list[Attempt], name: str, refusal: bool) -> Explanation:
    text = policy.validation.unsafe_template.format(reason=reason)
    return Explanation(
        AnalyticalAction.ANALYSIS_UNSAFE, finalize_text(policy, text, "", refusal), [], attempts, True, name
    )


OPENERS = ("", "Araç çıktılarına göre: ", "Kanıtlar şunu gösteriyor: ", "Özetle: ", "Geçmiş veriye bakıldığında: ")
GATE_LINES = (
    "Risk kapısı sonucu {gate} ({ids}).",
    "Risk ve veri kalitesi kapısı {gate} sonucunu verdi ({ids}).",
    "Kapı değerlendirmesi: {gate} ({ids}).",
)
CLOSINGS = (
    "",
    "Bu nedenle eğitsel analitik durum {action} olarak belirlenir.",
    "Sonuç olarak durum {action} etiketiyle izlenir.",
    "Kanıtlar birlikte değerlendirildiğinde uygun etiket {action}.",
)
LIMITS = (
    "Sonuçlar geçmiş veriye dayanır; korelasyon nedensellik değildir.",
    "Tarihsel istatistikler gelecekteki fiyat hareketini belirlemez.",
    "Bulgular örneklem büyüklüğü ve dönem seçimine duyarlıdır.",
)


@dataclass
class TemplateExplainer:
    """Deterministic explanation from the decision policy (no LLM): baseline and training teacher."""

    policy: Policy
    name: str = "template_v1"

    variant: int = 0  # phrasing variant (dataset generation varies it; inference uses 0)

    def compose(self, req: AnalysisRequest, bundle: dict[str, Any], gate: GateStatus) -> dict[str, Any]:
        d = decide(req, bundle["committed"], gate, self.policy.decision)
        v = self.variant
        by_id = {c["id"]: c for c in bundle["committed"]}
        facts = [c for c in bundle["committed"] if c["kind"] != "warning" and c["key"] != "gate.result"]
        warns = [c for c in bundle["committed"] if c["kind"] == "warning" and c["key"] != "gate.result"]
        # facts the decision relies on come first, then the others (a variant uses 4-6 of them)
        k = 4 + v % 3
        cited_first = [c for c in facts if c["id"] in d.cite]
        ordered = cited_first + [c for c in facts if c["id"] not in d.cite]
        if any(word in req.question.casefold() for word in ("video", "konuşma", "transkript")):
            speech = next((c for c in ordered if c["key"].startswith("speech_check.")), None)
            if speech is not None:
                ordered = [speech, *(c for c in ordered if c["id"] != speech["id"])]
        used = ordered[:k]
        used.sort(key=lambda c: int(c["id"][1:]))
        opener = OPENERS[v % len(OPENERS)]
        body = " ".join(f"{c['claim_tr'].rstrip('.')} ({c['id']})." for c in used)
        gate_ids = [c["id"] for c in bundle["committed"] if c["key"] == "gate.result"]
        gate_txt = GATE_LINES[v % len(GATE_LINES)].format(gate=gate.value, ids=", ".join(gate_ids)) if gate_ids else ""
        closing = CLOSINGS[v % len(CLOSINGS)].format(action=d.action.value)
        explanation = " ".join(x for x in (opener + body, d.rationale_tr, gate_txt, closing) if x)
        limitations = " ".join(f"{c['claim_tr'].rstrip('.')} ({c['id']})." for c in warns[:3])
        if not limitations:
            limitations = LIMITS[v % len(LIMITS)]
        cited = sorted(
            {*d.cite, *(c["id"] for c in used), *(c["id"] for c in warns[:3]), *gate_ids}, key=lambda x: int(x[1:])
        )
        return {
            "action": d.action.value,
            "explanation_tr": explanation,
            "cited_evidence": [c for c in cited if c in by_id],
            "refusal_needed": req.advice_requested,
            "limitations_tr": limitations,
            "_rule": d.rule,
        }

    def explain(self, req: AnalysisRequest, bundle: dict[str, Any], gate: GateStatus) -> Explanation:
        out = self.compose(req, bundle, gate)
        rule = out.pop("_rule")
        v = _validate(out, req, bundle, gate, self.policy)
        att = [Attempt(json.dumps(out, ensure_ascii=False), v, model=self.name)]
        if not v.ok or v.output is None:
            return unsafe(
                self.policy,
                "şablon açıklaması denetimden geçmedi: " + "; ".join(v.errors)[:200],
                att,
                self.name,
                req.advice_requested,
            )
        o = v.output
        return Explanation(
            o.action,
            finalize_text(self.policy, o.explanation_tr, o.limitations_tr, o.refusal_needed),
            o.cited_evidence,
            att,
            False,
            self.name,
            o.action,
            rule,
        )


@dataclass
class LLMExplainer:
    client: LLMClient
    policy: Policy
    name: str = "llm_explainer_v1"

    def explain(self, req: AnalysisRequest, bundle: dict[str, Any], gate: GateStatus) -> Explanation:
        allowed = sorted(a.value for a in ALLOWED_ACTIONS_BY_GATE[gate])
        schema = output_schema(allowed)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(req, bundle, gate)},
        ]
        attempts: list[Attempt] = []
        teacher = decide(req, bundle["committed"], gate, self.policy.decision)
        for _ in range(self.policy.validation.max_attempts):
            resp = self.client.chat(messages, schema)
            v = _validate(resp.text, req, bundle, gate, self.policy)
            attempts.append(
                Attempt(resp.text, v, resp.prompt_hash, resp.model, resp.digest, resp.seconds, list(messages))
            )
            if v.ok and v.output is not None:
                o = v.output
                refusal = o.refusal_needed or req.advice_requested
                return Explanation(
                    o.action,
                    finalize_text(self.policy, o.explanation_tr, o.limitations_tr, refusal),
                    o.cited_evidence,
                    attempts,
                    False,
                    self.name,
                    teacher.action,
                    teacher.rule,
                )
            messages = [
                *messages,
                {"role": "assistant", "content": resp.text},
                {"role": "user", "content": feedback_prompt(v)},
            ]
        e = unsafe(
            self.policy, "model çıktısı iki denemede de denetimden geçmedi", attempts, self.name, req.advice_requested
        )
        e.teacher_action, e.teacher_rule = teacher.action, teacher.rule
        return e
