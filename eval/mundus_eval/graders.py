"""Graders. Code graders are deterministic; the model grader uses Claude Fable 5.2 for the wording tasks."""
from __future__ import annotations

import json
import re
from typing import Any

GRADER_MODEL = "claude-fable-5-2"
_NUM = re.compile(r"(?<![\w.])\$?\s?(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s?(million|billion|m\b|k\b)?", re.I)
_MARKER = re.compile(r"\[claim:[0-9a-f]{6,32}\]")
_SCALE = {"million": 1e6, "m": 1e6, "billion": 1e9, "k": 1e3}


def numbers_in(text: str) -> list[float]:
    out = []
    for raw, scale in _NUM.findall(_MARKER.sub(" ", text)):
        try:
            out.append(float(raw.replace(",", "")) * _SCALE.get((scale or "").lower(), 1))
        except ValueError:
            pass
    return out


def check_number(answer: str, truth: Any, tolerance: float = 0.0) -> tuple[bool, str]:
    if truth is None:
        return False, "truth is missing"
    t = float(truth)
    for n in numbers_in(answer):
        if abs(n - t) <= abs(t) * tolerance + 1e-9:
            return True, f"found {n:g}"
    return False, f"expected {t:g} (tolerance {tolerance:g})"


def check_contains(answer: str, truth: Any) -> tuple[bool, str]:
    if truth in (None, ""):
        return False, "truth is missing"
    ok = str(truth).strip().lower() in answer.lower()
    return ok, f"{'found' if ok else 'missing'} '{truth}'"


def check_boolean(answer: str, truth: Any, true_words: list[str], false_words: list[str]) -> tuple[bool, str]:
    if truth is None:
        return False, "truth is missing"
    low = answer.lower()
    says_false = any(w in low for w in false_words)
    says_true = any(w in low for w in true_words) and not says_false
    if bool(truth):
        return says_true, "expected a statement that it is present"
    return says_false, "expected a statement that it is absent"


def check_order(answer: str, first: str, last: str) -> tuple[bool, str]:
    """True when one clause ties `first` to "most" and another ties `last` to "fewest"."""
    most = re.compile(r"\b(most|highest|largest number|greatest)\b")
    few = re.compile(r"\b(fewest|least|lowest|smallest number)\b")
    clauses = [c for c in re.split(r"[.;\n]|\bwhile\b|\bwhereas\b|, and\b|, but\b", answer.lower()) if c.strip()]
    f, la = first.lower(), last.lower()
    ok_first = any(f in c and most.search(c) and not (la in c and not few.search(c)) for c in clauses)
    ok_last = any(la in c and few.search(c) and not (f in c and not most.search(c)) for c in clauses)
    wrong = any(f in c and few.search(c) and not most.search(c) for c in clauses) or \
        any(la in c and most.search(c) and not few.search(c) for c in clauses)
    return ok_first and ok_last and not wrong, f"'{first}' should be the most and '{last}' the fewest"


def citation_coverage(answer: str) -> float:
    """Share of sentences containing a digit that also carry a claim marker."""
    # a marker placed after the full stop belongs to the sentence before it
    answer = re.sub(r"([.!?])((?:\s*\[claim:[0-9a-f]{6,32}\])+)", r"\2\1", answer)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", answer) if s.strip()]
    factual = [s for s in sentences if re.search(r"\d", _MARKER.sub("", s))]
    if not factual:
        return 1.0
    return sum(1 for s in factual if _MARKER.search(s)) / len(factual)


def grade_code(task: dict[str, Any], truth: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """run: {answer, citations:[{claim_id, evidence_ids}], dropped_markers, evidence_types, claims:[...], metrics}."""
    answer = run.get("answer") or ""
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    for c in task.get("checks") or []:
        key = c.get("key")
        if c["type"] == "number":
            add(f"number:{key}", *check_number(answer, truth.get(key), c.get("tolerance", 0.0)))
        elif c["type"] == "contains":
            add(f"contains:{key}", *check_contains(answer, truth.get(key)))
        elif c["type"] == "boolean":
            add(f"boolean:{key}", *check_boolean(answer, truth.get(key), c["true_words"], c["false_words"]))
        elif c["type"] == "order":
            add("order", *check_order(answer, c["first"], c["last"]))
        else:
            add(f"unknown:{c['type']}", False, "unknown check type")
    checks += common_checks(task, run)
    return {"grader": "code", "pass": all(c["ok"] for c in checks if c["check"] not in SOFT), "checks": checks,
            "score": round(sum(c["ok"] for c in checks) / max(1, len(checks)), 3)}


SOFT = {"citation_coverage", "budget"}
_NEGATED = re.compile(r"\b(no|not|none|cannot|can't|unknown|lacks?|without|absent|unavailable|does not|do not|isn't|aren't)\b", re.I)


def common_checks(task: dict[str, Any], run: dict[str, Any]) -> list[dict[str, Any]]:
    """Checks that apply to every task: citations resolve, required evidence was used, nothing forbidden was written."""
    out: list[dict[str, Any]] = []
    answer = run.get("answer") or ""
    dropped = run.get("dropped_markers") or []
    cites = run.get("citations") or []
    expect_refusal = bool(task.get("expect_refusal"))
    out.append({"check": "citation_validity", "ok": not dropped and (bool(cites) or expect_refusal or not numbers_in(answer)),
                "detail": f"{len(cites)} valid, {len(dropped)} unresolved"})
    cov = citation_coverage(answer)
    out.append({"check": "citation_coverage", "ok": cov >= 0.999, "detail": f"{cov:.0%} of numeric sentences cited"})
    need = set(task.get("required_evidence_types") or [])
    have = set(run.get("evidence_types") or [])
    out.append({"check": "evidence_types", "ok": need <= have, "detail": f"need {sorted(need)}, cited {sorted(have)}"})
    pats = [p.lower() for p in task.get("forbidden_claim_patterns") or []]
    if pats:
        # A claim that says the data lacks something ("there is no structural data on beams") is correct behaviour,
        # not an invention: only statements that assert the forbidden thing count.
        bad = [c["statement"] for c in run.get("claims") or []
               if any(p in c.get("statement", "").lower() for p in pats) and not _NEGATED.search(c.get("statement", ""))]
        out.append({"check": "no_invented_claims", "ok": not bad, "detail": f"{len(bad)} forbidden claims written"})
    m = run.get("metrics") or {}
    out.append({"check": "budget", "ok": (m.get("model_calls") or 0) < 60, "detail": f"{m.get('model_calls')} model calls"})
    return out


GRADER_SYSTEM = """You grade one answer from an AI agent that answers questions about buildings using a fixed data set.
You are given the question, a rubric, reference facts computed from the data, and sometimes a visual reference written
from the actual photographs. Grade strictly against the rubric and the references. Do not use outside knowledge of the
buildings. An answer that states something the references contradict, or states a specific fact the data does not
contain, fails that part even if it sounds plausible. Declining to invent is correct behaviour when the rubric says the
data lacks the information.

Reply with one JSON object and nothing else:
{"score": <number from 0 to 1>, "pass": <true|false>, "reasons": ["short reason", ...], "unsupported_statements": ["..."]}
pass is true only when the rubric's full-marks or half-marks conditions are met with no fail condition triggered."""


def grade_model(task: dict[str, Any], truth: dict[str, Any], reference: str | None, run: dict[str, Any],
                client: Any = None) -> dict[str, Any]:
    """Scores a wording task with Claude Fable 5.2. Thinking is always on for this model, so no thinking parameter is sent."""
    import anthropic
    from mundus_harness.tracing import wrap_anthropic

    client = client or wrap_anthropic(anthropic.Anthropic(), name="grader")
    facts = {k: v for k, v in truth.items() if not k.startswith("_")}
    prompt = (f"QUESTION:\n{task['question']}\n\nRUBRIC:\n{task['rubric']}\n\nREFERENCE FACTS (from the data):\n"
              f"{json.dumps(facts, indent=1, ensure_ascii=False)}\n\nVISUAL REFERENCE (from the photographs):\n"
              f"{reference or 'none for this task'}\n\nAGENT ANSWER:\n{run.get('answer') or '(empty)'}\n\n"
              f"CLAIMS THE AGENT WROTE TO MEMORY DURING THE RUN:\n"
              f"{json.dumps([c.get('statement') for c in run.get('claims') or []], ensure_ascii=False)}")
    checks = common_checks(task, run)
    try:
        resp = client.beta.messages.create(
            model=GRADER_MODEL, max_tokens=16000, system=GRADER_SYSTEM, output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": prompt}])
    except anthropic.APIStatusError as e:
        return {"grader": "model", "pass": False, "score": 0.0, "error": f"grader call failed: {e.status_code}", "checks": checks}
    except anthropic.APIConnectionError:
        return {"grader": "model", "pass": False, "score": 0.0, "error": "grader call failed: network", "checks": checks}
    if resp.stop_reason == "refusal":
        return {"grader": "model", "pass": False, "score": 0.0, "error": "grader declined", "checks": checks}
    text = "".join(b.text for b in resp.content if b.type == "text")
    verdict = parse_verdict(text)
    hard_ok = all(c["ok"] for c in checks if c["check"] not in SOFT)
    return {"grader": "model", "grader_model": resp.model, "pass": bool(verdict["pass"]) and hard_ok, "score": verdict["score"],
            "reasons": verdict["reasons"], "unsupported_statements": verdict["unsupported_statements"], "checks": checks,
            "grader_tokens": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}}


def parse_verdict(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    score = d.get("score")
    try:
        score = max(0.0, min(1.0, float(score)))
    except (TypeError, ValueError):
        score = 0.0
    return {"score": score, "pass": d.get("pass") is True, "reasons": [str(x) for x in d.get("reasons") or []][:8],
            "unsupported_statements": [str(x) for x in d.get("unsupported_statements") or []][:8]}
