"""Retrieval metrics over labeled items, not chunks (SDD section 13, Q-13 policy approved 2026-11-07).

Each retrieved chunk maps to the set of labeled items it matches. An item found twice counts once, so a
long passage split over two chunks is not rewarded twice. Recall@K and MRR are P0; Precision@K and nDCG@K are
P1 (Phase 10) under the same policy ID.

A position is credited when it holds at least one relevant item that no earlier position held. Precision@K
counts credited positions over K, and nDCG@K gives each credited position the gain of the highest-graded item it
newly finds. Both therefore stay within 0 and 1, even for a chunk that matches two labeled items.
"""

import math
import random

K_VALUES = (1, 3, 5)
METRIC_POLICY = "q13-v1"
P0_METRICS = tuple(f"recall@{k}" for k in K_VALUES) + ("mrr",)
P1_METRICS = tuple(f"precision@{k}" for k in K_VALUES) + tuple(f"ndcg@{k}" for k in K_VALUES)
METRICS = P0_METRICS + P1_METRICS

# Paired bootstrap for P10-6, fixed before any hybrid or reranker result exists.
BOOTSTRAP_POLICY = "paired-bootstrap-percentile-v1"
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20261113
BOOTSTRAP_CONFIDENCE = 0.95


def recall_at_k(matches: list[set[str]], relevant: set[str], k: int) -> float:
    """Relevant items found in the first k results / relevant items labeled."""
    if not relevant:
        raise ValueError("recall is undefined without relevant items")
    found = set().union(*matches[:k]) & relevant
    return len(found) / len(relevant)


def reciprocal_rank(matches: list[set[str]], relevant: set[str]) -> float:
    """1 / rank of the first result matching any relevant item; 0 if none is returned."""
    if not relevant:
        raise ValueError("reciprocal rank is undefined without relevant items")
    return next((1 / rank for rank, items in enumerate(matches, 1) if items & relevant), 0.0)


def credited(matches: list[set[str]], relevant: set[str], k: int) -> list[set[str]]:
    """For each of the first k positions, the relevant items it is the first to hold."""
    seen, found = set(), []
    for items in matches[:k]:
        new = (items & relevant) - seen
        seen |= new
        found.append(new)
    return found


def precision_at_k(matches: list[set[str]], relevant: set[str], k: int) -> float:
    """Credited positions in the first k results / k. Missing results count as misses."""
    if not relevant:
        raise ValueError("precision is undefined without relevant items")
    return sum(1 for new in credited(matches, relevant, k) if new) / k


def gain(grade: int) -> float:
    return 2 ** grade - 1


def ndcg_at_k(matches: list[set[str]], grades: dict[str, int], k: int) -> float:
    """DCG of the credited positions over the ideal DCG of the labeled relevant items, both cut at k.

    Gain is 2^grade - 1 and the discount is log2(rank + 1). The ideal ranks the labeled items by grade, one per position.
    """
    relevant = {item for item, grade in grades.items() if grade > 0}
    if not relevant:
        raise ValueError("nDCG is undefined without relevant items")
    dcg = sum(max(gain(grades[item]) for item in new) / math.log2(rank + 1)
              for rank, new in enumerate(credited(matches, relevant, k), 1) if new)
    ideal = sorted((grades[item] for item in relevant), reverse=True)[:k]
    return dcg / sum(gain(grade) / math.log2(rank + 1) for rank, grade in enumerate(ideal, 1))


def question_metrics(matches: list[set[str]], grades: dict[str, int]) -> dict[str, float]:
    """Every metric for one answerable question. `grades` maps each labeled item to its grade; grade 0 is not relevant."""
    relevant = {item for item, grade in grades.items() if grade > 0}
    values = {f"recall@{k}": recall_at_k(matches, relevant, k) for k in K_VALUES}
    values["mrr"] = reciprocal_rank(matches, relevant)
    values.update({f"precision@{k}": precision_at_k(matches, relevant, k) for k in K_VALUES})
    values.update({f"ndcg@{k}": ndcg_at_k(matches, grades, k) for k in K_VALUES})
    return values


def macro_average(rows: list[dict[str, float]], names=METRICS) -> dict[str, float | None]:
    """Unweighted mean over questions; None, not zero, when there is nothing to average."""
    return {name: (sum(row[name] for row in rows) / len(rows) if rows else None) for name in names}


def p95(values: list[float]) -> float | None:
    """Nearest-rank 95th percentile: the ceil(0.95 n)-th smallest value, in integer arithmetic."""
    if not values:
        return None
    return sorted(values)[-(-95 * len(values) // 100) - 1]


def paired_bootstrap(differences: list[float], resamples: int = BOOTSTRAP_RESAMPLES, seed: int = BOOTSTRAP_SEED,
                     confidence: float = BOOTSTRAP_CONFIDENCE) -> dict:
    """Mean of per-question differences (candidate minus baseline) with a percentile bootstrap interval.

    Questions are resampled with replacement, the same draw for both configurations, from a generator seeded afresh
    for each comparison, so the interval can be recomputed from the stored per-question values. The interval drops
    round(resamples * (1 - confidence) / 2) sorted means from each end: for 10,000 at 95%, the 251st and the 9,750th.
    """
    if not differences:
        raise ValueError("the bootstrap needs at least one paired question")
    generator, n = random.Random(seed), len(differences)
    means = sorted(sum(differences[generator.randrange(n)] for _ in range(n)) / n for _ in range(resamples))
    trimmed = round(resamples * (1 - confidence) / 2)
    return {"n": n, "mean_difference": sum(differences) / n,
            "interval": [means[trimmed], means[resamples - 1 - trimmed]],
            "better": sum(1 for value in differences if value > 0), "worse": sum(1 for value in differences if value < 0),
            "tied": sum(1 for value in differences if value == 0)}
