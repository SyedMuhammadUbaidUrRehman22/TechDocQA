"""Calibrated pre-generation sufficiency (FR-18): one 0-1 relevance scale and one threshold set per retrieval mode (Q-07).

Vector relevance is the FR-12 score, (cosine + 1) / 2. BM25 relevance is the raw score over the most that query could
score (retrieval/lexical.py), which keeps both the ranking and the raw score. Thresholds come from a smoke-benchmark run
and apply only while the scale they were chosen on is the active one, so no mode, embedding model or BM25 setting
reuses another's. The gate judges the chunks kept for the prompt, so a chunk dropped to fit the window cannot pass it.
"""

from techdocqa.schemas import ComponentCheck, SearchResult, SufficiencyCheck
from techdocqa.settings import HybridThresholds, SufficiencyThresholds

NOT_CALIBRATED = "SUFFICIENCY_NOT_CALIBRATED"
STALE = "SUFFICIENCY_CALIBRATION_STALE"
CALIBRATION_POLICY = "balanced-accuracy-midpoint-v1"
DIGITS = 6
# Hybrid gate candidates G1 to G4 (P10-3), in the order that breaks a final tie.
GATES = ("vector", "bm25", "either", "both")
GATE_COMPONENTS = {"vector": ("vector",), "bm25": ("bm25",), "either": ("bm25", "vector"), "both": ("bm25", "vector")}
HYBRID_SELECTION_POLICY = "fewest-loo-errors-then-margin-then-order-v1"


def relevance_policy(mode: str) -> str:
    from techdocqa.indexing.embeddings import SCORE_POLICY
    from techdocqa.retrieval.lexical import RELEVANCE_POLICY
    from techdocqa.retrieval.search import HYBRID_RELEVANCE_POLICY
    return {"bm25": RELEVANCE_POLICY, "vector": SCORE_POLICY, "hybrid": HYBRID_RELEVANCE_POLICY}[mode]


def active_thresholds(mode: str, settings, profile: dict | None) -> tuple[SufficiencyThresholds | HybridThresholds | None, str | None]:
    """The mode's thresholds when they were calibrated on the active score scale; otherwise None and the warning to show."""
    from techdocqa.retrieval.search import scoring_config_id
    sections = settings.retrieval.sufficiency
    configured = {"bm25": sections.bm25, "vector": sections.vector, "hybrid": sections.hybrid}.get(mode)
    if configured is None:
        return None, NOT_CALIBRATED
    if configured.scoring_config_id != scoring_config_id(mode, settings, profile):
        return None, STALE
    return configured, None


def judge(relevances: list[float], thresholds: SufficiencyThresholds) -> tuple[int, bool]:
    """Supporting chunks and the verdict: the best chunk meets min_top_score and enough chunks meet min_chunk_score."""
    supporting = sum(1 for value in relevances if value >= thresholds.min_chunk_score)
    passed = bool(relevances) and max(relevances) >= thresholds.min_top_score and supporting >= thresholds.min_supporting_chunks
    return supporting, passed


def judge_gate(values: dict[str, list[float]], thresholds: HybridThresholds) -> tuple[dict[str, tuple[int, bool]], bool]:
    """Hybrid: each judged component's (supporting chunks, verdict) on its own relevances, and the gate's verdict.

    A chunk without a component relevance, such as one not yet in the vector index, does not count for that component.
    """
    checks = {name: judge(values.get(name, []), levels) for name, levels in thresholds.components().items()}
    verdicts = [passed for _, passed in checks.values()]
    return checks, any(verdicts) if thresholds.gate == "either" else all(verdicts)


def new_check(mode: str, thresholds: SufficiencyThresholds | HybridThresholds | None, *,
              thresholds_from: str | None = None) -> SufficiencyCheck:
    """thresholds_from names the surviving mode when degraded hybrid is judged by that mode's own thresholds."""
    if isinstance(thresholds, HybridThresholds):
        return SufficiencyCheck(calibrated=True, relevance_policy=relevance_policy(mode), gate=thresholds.gate,
                                calibration_run_id=thresholds.calibration_run_id)
    values = thresholds.model_dump(exclude={"scoring_config_id"}) if thresholds else {}
    return SufficiencyCheck(calibrated=thresholds is not None, relevance_policy=relevance_policy(thresholds_from or mode),
                            thresholds_from=thresholds_from, **values)


def record(check: SufficiencyCheck, kept: list[SearchResult], thresholds: SufficiencyThresholds | HybridThresholds | None) -> SufficiencyCheck:
    """Judges the kept chunks. The verdict uses exact scores; the response shows them rounded."""
    if isinstance(thresholds, HybridThresholds):
        values = {name: [result.relevances[name] for result in kept if result.relevances.get(name) is not None]
                  for name in thresholds.components()}
        checks, check.passed = judge_gate(values, thresholds)
        check.components = {name: ComponentCheck(passed=passed, supporting_chunks=supporting,
                                                 top_score=round(max(values[name]), DIGITS) if values[name] else None,
                                                 **thresholds.components()[name].model_dump())
                            for name, (supporting, passed) in checks.items()}
        return check
    relevances = [result.relevance for result in kept if result.relevance is not None]
    check.top_score = round(max(relevances), DIGITS) if relevances else None
    if thresholds is not None:
        check.supporting_chunks, check.passed = judge(relevances, thresholds)
    return check


def choose(answerable: list[float | None], unanswerable: list[float | None]) -> float | None:
    """The midpoint between neighboring top scores with the best balanced accuracy; a tie goes to the wider gap.

    None is a question that retrieved nothing: answerable, it fails any threshold; unanswerable, it is refused anyway.
    When the groups separate, this is the middle of the gap between the weakest answerable and the strongest unanswerable.
    """
    scores = sorted({score for score in [*answerable, *unanswerable] if score is not None})
    if not answerable or not unanswerable or len(scores) < 2:
        return None
    best = None
    for low, high in zip(scores, scores[1:]):
        threshold = (low + high) / 2
        passed, refused = outcome(threshold, answerable, unanswerable)
        key = (passed / len(answerable) + refused / len(unanswerable), high - low)
        if best is None or key > best[0]:
            best = key, threshold
    return round(best[1], DIGITS)


def outcome(threshold: float, answerable: list[float | None], unanswerable: list[float | None]) -> tuple[int, int]:
    """(answerable questions passing, unanswerable questions refused) by the top score alone."""
    passed = sum(1 for score in answerable if score is not None and score >= threshold)
    refused = sum(1 for score in unanswerable if score is None or score < threshold)
    return passed, refused


def leave_one_out_errors(answerable: list[float | None], unanswerable: list[float | None]) -> int:
    """Questions misjudged by the threshold chosen without them: a small-sample check of how well the choice holds up."""
    errors = 0
    for is_answerable, group in ((True, answerable), (False, unanswerable)):
        for index, score in enumerate(group):
            rest = group[:index] + group[index + 1:]
            threshold = choose(rest, unanswerable) if is_answerable else choose(answerable, rest)
            if threshold is None:
                continue
            passes = score is not None and score >= threshold
            errors += passes != is_answerable
    return errors


def propose(answerable: list[float | None], unanswerable: list[float | None]) -> dict | None:
    """Thresholds for one mode from its smoke-benchmark top scores, or None when either group is empty.

    With one supporting chunk required, min_chunk_score equals min_top_score: the smoke set has too few questions to
    calibrate a second, independent threshold.
    """
    threshold = choose(answerable, unanswerable)
    if threshold is None:
        return None
    passed, refused = outcome(threshold, answerable, unanswerable)
    scores = [score for score in [*answerable, *unanswerable] if score is not None]
    return {"policy": CALIBRATION_POLICY, "min_top_score": threshold, "min_chunk_score": threshold, "min_supporting_chunks": 1,
            "margin": round(min(abs(score - threshold) for score in scores), DIGITS),
            "separable": (passed, refused) == (len(answerable), len(unanswerable)),
            "answerable": len(answerable), "answerable_passed": passed,
            "unanswerable": len(unanswerable), "unanswerable_refused": refused,
            "leave_one_out_errors": leave_one_out_errors(answerable, unanswerable)}


def toml_block(mode: str, proposal: dict, run_id: str, scoring_config_id: str) -> str:
    """The configuration section that adopts a proposal; settings never change unless a person pastes it in."""
    return "\n".join([f"[retrieval.sufficiency.{mode}]",
                      f"min_top_score = {proposal['min_top_score']}", f"min_chunk_score = {proposal['min_chunk_score']}",
                      f"min_supporting_chunks = {proposal['min_supporting_chunks']}",
                      f'calibration_run_id = "{run_id}"', f'scoring_config_id = "{scoring_config_id}"'])


# Hybrid proposals (P10-3). Each question is summarized per component by the best relevance among its top results,
# which is what the gate's min_top_score judges; None when no result has that component's relevance.

def gate_passes(gate: str, tops: dict[str, float | None], thresholds: dict[str, float]) -> bool:
    verdicts = [tops.get(name) is not None and tops[name] >= thresholds[name] for name in GATE_COMPONENTS[gate]]
    return any(verdicts) if gate == "either" else all(verdicts)


def gate_distance(gate: str, tops: dict[str, float | None], thresholds: dict[str, float]) -> float | None:
    """How far a question's deciding relevance is from its threshold, the unit of a gate's margin.

    Either passes on its best component and both on its worst, so those decide. A question missing a component under
    "both" fails at any threshold, and one with no relevance at all cannot flip; neither has a distance.
    """
    names = GATE_COMPONENTS[gate]
    distances = [tops[name] - thresholds[name] for name in names if tops.get(name) is not None]
    if not distances or (gate == "both" and len(distances) < len(names)):
        return None
    return abs(max(distances) if gate == "either" else min(distances))


def gate_thresholds(gate: str, answerable: list[dict], unanswerable: list[dict]) -> dict[str, float] | None:
    """Each component's threshold chosen on its own scale, as for a single mode; G3 and G4 combine G1's and G2's."""
    found = {name: choose([tops.get(name) for tops in answerable], [tops.get(name) for tops in unanswerable])
             for name in GATE_COMPONENTS[gate]}
    return None if any(value is None for value in found.values()) else found


def gate_leave_one_out_errors(gate: str, answerable: list[dict], unanswerable: list[dict]) -> int:
    """Questions misjudged when every threshold the gate uses is re-chosen without them."""
    errors = 0
    for is_answerable, group in ((True, answerable), (False, unanswerable)):
        for index, tops in enumerate(group):
            rest = group[:index] + group[index + 1:]
            thresholds = gate_thresholds(gate, rest, unanswerable) if is_answerable else gate_thresholds(gate, answerable, rest)
            if thresholds is not None:
                errors += gate_passes(gate, tops, thresholds) != is_answerable
    return errors


def propose_hybrid(answerable: list[dict], unanswerable: list[dict]) -> dict | None:
    """Every gate's proposal and the one selected: fewest leave-one-out errors, then the largest margin, then the order
    G1 to G4. Margins are compared raw, although vector relevance spans a narrower range than BM25's."""
    candidates = []
    for gate in GATES:
        thresholds = gate_thresholds(gate, answerable, unanswerable)
        if thresholds is None:
            continue
        passed = sum(1 for tops in answerable if gate_passes(gate, tops, thresholds))
        refused = sum(1 for tops in unanswerable if not gate_passes(gate, tops, thresholds))
        distances = [value for tops in [*answerable, *unanswerable] if (value := gate_distance(gate, tops, thresholds)) is not None]
        candidates.append({"gate": gate, "thresholds": thresholds,
                           "margin": round(min(distances), DIGITS) if distances else None,
                           "separable": (passed, refused) == (len(answerable), len(unanswerable)),
                           "answerable": len(answerable), "answerable_passed": passed,
                           "unanswerable": len(unanswerable), "unanswerable_refused": refused,
                           "leave_one_out_errors": gate_leave_one_out_errors(gate, answerable, unanswerable)})
    if not candidates:
        return None
    selected = min(candidates, key=lambda item: (item["leave_one_out_errors"],
                                                 -item["margin"] if item["margin"] is not None else float("inf"),
                                                 GATES.index(item["gate"])))
    return {"policy": CALIBRATION_POLICY, "selection_policy": HYBRID_SELECTION_POLICY, **selected, "candidates": candidates}


def hybrid_toml_block(proposal: dict, run_id: str, scoring_config_id: str) -> str:
    """The section that adopts a hybrid proposal, with one table per judged component."""
    lines = ["[retrieval.sufficiency.hybrid]", f'gate = "{proposal["gate"]}"', f'calibration_run_id = "{run_id}"',
             f'scoring_config_id = "{scoring_config_id}"']
    for name in GATE_COMPONENTS[proposal["gate"]]:
        threshold = proposal["thresholds"][name]
        lines += ["", f"[retrieval.sufficiency.hybrid.{name}]", f"min_top_score = {threshold}", f"min_chunk_score = {threshold}",
                  "min_supporting_chunks = 1"]
    return "\n".join(lines)

