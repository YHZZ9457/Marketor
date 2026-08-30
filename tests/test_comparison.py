from csi300_service.comparison import MarketComparisonService, allocation_scores


def test_allocation_scores_are_bounded_and_cumulative():
    buy, sell = allocation_scores({
        "bias250": -0.16, "bias500": -0.1, "bias1250": -0.12,
        "rsi14": 28, "drawdown_250d": -0.25,
    })
    assert buy == 100
    assert sell == 0


def test_comparison_contains_rank_and_percentiles():
    rows = MarketComparisonService().snapshots()
    assert len(rows) >= 6
    assert [row["rank"] for row in rows] == list(range(1, len(rows) + 1))
    assert all(0 <= row["buy_score"] <= 100 for row in rows)
    assert all(0 <= row["relative_value_score"] <= 100 for row in rows)
    assert rows == sorted(rows, key=lambda row: (row["ranking_score"], row["buy_score"]), reverse=True)
