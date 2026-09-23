"""
Прогноз риска брака на основе внутренних признаков протокола.
"""
from typing import Any, Dict, List

from logger import logger


LABEL_RU = {
    "low": "низкий",
    "medium": "средний",
    "high": "высокий",
    "critical": "критический",
}


def predict_risk(rows_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not rows_results:
        return {"risk_percent": 0, "label": "low", "label_ru": LABEL_RU["low"],
                "factors": [], "avg_deviation": 0, "problem_ratio": 0}

    total_rows = len(rows_results)
    defect_rows = sum(1 for r in rows_results if r["overall_status"] == "defect")
    warning_rows = sum(1 for r in rows_results if r["overall_status"] == "warning")

    problem_ratio = (defect_rows + 0.5 * warning_rows) / total_rows

    # Средняя величина отклонений
    deviations = []
    for r in rows_results:
        for p in r["parameters"]:
            if p["status"] in ("fail", "warning"):
                try:
                    actual = float(p["actual"])
                    norm_str = str(p.get("norm", ""))
                    for prefix in ("≤ ", "≥ "):
                        if norm_str.startswith(prefix):
                            norm_str = norm_str[len(prefix):]
                            break
                    norm_str = norm_str.split()[0].replace(",", ".")
                    norm = float(norm_str)
                    if norm != 0:
                        deviations.append(abs(actual - norm) / abs(norm) * 100)
                except (ValueError, TypeError):
                    continue

    avg_deviation = sum(deviations) / len(deviations) if deviations else 0
    concentration = defect_rows / max(total_rows, 1)

    risk = 0.0
    risk += problem_ratio * 50
    risk += min(avg_deviation, 30) * 0.8
    risk += concentration * 20
    risk = min(round(risk, 1), 99.0)

    if risk < 15:
        label = "low"
    elif risk < 40:
        label = "medium"
    elif risk < 70:
        label = "high"
    else:
        label = "critical"

    factors = []
    if problem_ratio > 0.3:
        factors.append(f"{int(problem_ratio * 100)}% партий с отклонениями")
    if avg_deviation > 5:
        factors.append(f"среднее отклонение {round(avg_deviation, 1)}%")
    if concentration > 0.2:
        factors.append(f"{defect_rows} критически забракованных партий")

    return {
        "risk_percent": risk,
        "label": label,
        "label_ru": LABEL_RU[label],
        "factors": factors,
        "avg_deviation": round(avg_deviation, 2),
        "problem_ratio": round(problem_ratio, 3),
    }