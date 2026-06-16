"""
score.py — Daily: compare forecasts against real results and update scores.

Scoring tiers (per model per match, cumulative):
  - Exact score:          3 pts
  - Correct result W/D/L: 1 pt   (not awarded if exact score already counted)
  - Goal diff within 1:  +0.5 bonus

Special handling:
  - Gemini: scored as two separate models (Gemini-1 for scenario_1, Gemini-2 for scenario_2)
  - Claude: confidence % applied as multiplier on the result tiers
            (exact score tier is NOT multiplied)
"""

import sqlite3

DB_PATH = "forecasts.db"


def result_sign(home: int, away: int) -> int:
    """Return 1 for home win, 0 for draw, -1 for away win."""
    if home > away:
        return 1
    if home < away:
        return -1
    return 0


def score_prediction(home_pred: int, away_pred: int,
                     home_actual: int, away_actual: int,
                     confidence: float | None = None,
                     model_name: str | None = None) -> dict:
    """Score a single prediction against actual result.

    Returns dict with exact_score, correct_result, goal_diff_bonus, total.
    """
    exact = (home_pred == home_actual and away_pred == away_actual)
    pred_sign = result_sign(home_pred, away_pred)
    actual_sign = result_sign(home_actual, away_actual)
    correct_result = (pred_sign == actual_sign)

    pred_diff = home_pred - away_pred
    actual_diff = home_actual - away_actual
    diff_within_1 = abs(pred_diff - actual_diff) <= 1

    exact_score_pts = 3 if exact else 0
    correct_result_pts = 1 if (correct_result and not exact) else 0
    goal_diff_bonus = 0.5 if diff_within_1 else 0.0

    is_claude = (model_name == "claude")
    use_confidence = is_claude and confidence is not None

    if use_confidence and not exact:
        correct_result_pts *= confidence
        goal_diff_bonus *= confidence
    elif use_confidence and exact:
        goal_diff_bonus *= confidence

    total = exact_score_pts + correct_result_pts + goal_diff_bonus

    return {
        "exact_score": exact_score_pts,
        "correct_result": round(correct_result_pts, 4),
        "goal_diff_bonus": round(goal_diff_bonus, 4),
        "total": round(total, 4),
    }


def main() -> None:
    conn = sqlite3.connect(DB_PATH)

    # Load model names
    cur = conn.execute("SELECT id, name FROM models")
    models = dict(cur.fetchall())  # {id: name}

    # Clear previous scores so re-running is idempotent
    conn.execute("DELETE FROM scores")
    conn.commit()

    # Fetch all predictions that have a corresponding result
    rows = conn.execute("""
        SELECT p.id, p.model_id, p.home_score, p.away_score,
               p.confidence, r.home_score, r.away_score
        FROM predictions p
        JOIN results r ON r.match_id = p.match_id
    """).fetchall()

    if not rows:
        print("No predictions with matching results to score.")
        conn.close()
        return

    inserted = 0
    errors = 0
    for row in rows:
        pred_id, model_id, pred_h, pred_a, confidence, actual_h, actual_a = row
        model_name = models.get(model_id, "")

        result = score_prediction(
            home_pred=pred_h, away_pred=pred_a,
            home_actual=actual_h, away_actual=actual_a,
            confidence=confidence, model_name=model_name,
        )

        try:
            conn.execute(
                """INSERT OR REPLACE INTO scores
                   (prediction_id, exact_score, correct_result,
                    goal_diff_bonus, total)
                   VALUES (?, ?, ?, ?, ?)""",
                (pred_id, result["exact_score"], result["correct_result"],
                 result["goal_diff_bonus"], result["total"]),
            )
            inserted += 1
        except sqlite3.Error as e:
            print(f"  ERROR inserting score for prediction {pred_id}: {e}")
            errors += 1

    conn.commit()

    # Summary per model
    print(f"\nScored {inserted} predictions ({errors} errors).\n")

    if inserted:
        cur = conn.execute("""
            SELECT m.display_name,
                   ROUND(AVG(s.total), 3) AS avg_score,
                   SUM(s.exact_score + s.correct_result + s.goal_diff_bonus) AS total_score,
                   COUNT(*) AS n
            FROM scores s
            JOIN predictions p ON p.id = s.prediction_id
            JOIN models m ON m.id = p.model_id
            JOIN results r ON r.match_id = p.match_id
            GROUP BY m.id
            ORDER BY avg_score DESC
        """)
        print(f"{'Model':<12} {'Avg':>7} {'Total':>7} {'Matches':>8}")
        print("-" * 36)
        for name, avg, total, n in cur:
            print(f"{name:<12} {avg:>7.3f} {total:>7.2f} {n:>8}")

    conn.close()


if __name__ == "__main__":
    main()
