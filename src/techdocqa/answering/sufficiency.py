"""Calibrated pre-generation sufficiency (FR-18): one 0-1 relevance scale and one threshold set per retrieval mode (Q-07).

Vector relevance is the FR-12 score, (cosine + 1) / 2. BM25 relevance is the raw score over the most that query could
score (retrieval/lexical.py), which keeps both the ranking and the raw score. Thresholds come from a smoke-benchmark run
and apply only while the scale they were chosen on is the active one, so no mode, embedding model or BM25 setting
reuses another's. The gate judges the chunks kept for the prompt, so a chunk dropped to fit the window cannot pass it.
"""

from techdocqa.schemas import SearchResult, SufficiencyCheck
from techdocqa.settings import SufficiencyThresholds

NOT_CALIBRATED = "SUFFICIENCY_NOT_CALIBRATED"
STALE = "SUFFICIENCY_CALIBRATION_STALE"
CALIBRATION_POLICY = "balanced-accuracy-midpoint-v1"
DIGITS = 6


def relevance_policy(mode: str) -> str:
    from techdocqa.indexing.embeddings import SCORE_POLICY
    from techdocqa.retrieval.lexical import RELEVANCE_POLICY
    return SCORE_POLICY if mode == "vector" else RELEVANCE_POLICY


def active_thresholds(mode: str, settings, profile: dict | None) -> tuple[SufficiencyThresholds | None, str | None]:
    """The mode's thresholds when they were calibrated on the active score scale; otherwise None and the warning to show."""
    from techdocqa.retrieval.search import scoring_config_id
    configured = getattr(settings.retrieval.sufficiency, mode, None)
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


def new_check(mode: str, thresholds: SufficiencyThresholds | None) -> SufficiencyCheck:
    values = thresholds.model_dump(exclude={"scoring_config_id"}) if thresholds else {}
    return SufficiencyCheck(calibrated=thresholds is not None, relevance_policy=relevance_policy(mode), **values)


def record(check: SufficiencyCheck, kept: list[SearchResult], thresholds: SufficiencyThresholds | None) -> SufficiencyCheck:
    """Judges the kept chunks. The verdict uses exact scores; the response shows them rounded."""
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
