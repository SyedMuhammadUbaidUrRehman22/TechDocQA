"""P0 retrieval metrics over labeled items, not chunks (SDD section 13, proposed Q-13 policy).

Each retrieved chunk maps to the set of labeled items it matches. An item found twice counts once, so a
long passage split over two chunks is not rewarded twice. Precision@K and nDCG@K are P1.
"""

K_VALUES = (1, 3, 5)
METRIC_POLICY = "q13-proposed-v1"


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


def question_metrics(matches: list[set[str]], relevant: set[str]) -> dict[str, float]:
    values = {f"recall@{k}": recall_at_k(matches, relevant, k) for k in K_VALUES}
    values["mrr"] = reciprocal_rank(matches, relevant)
    return values


def macro_average(rows: list[dict[str, float]]) -> dict[str, float | None]:
    """Unweighted mean over questions; None, not zero, when there is nothing to average."""
    names = [f"recall@{k}" for k in K_VALUES] + ["mrr"]
    return {name: (sum(row[name] for row in rows) / len(rows) if rows else None) for name in names}
