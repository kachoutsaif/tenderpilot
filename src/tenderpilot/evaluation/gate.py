"""Porte qualité : la CI échoue si la recherche est devenue moins bonne que la référence.

La référence (eval/reference.json) contient les scores du corpus figé au moment où elle a
été enregistrée. Une modification est refusée si un score descend sous

    seuil = référence - tolérance          (tolérance par défaut : 0,02)

Pourquoi 0,02 ? Le corpus a 26 questions notées (les 4 « hors sujet » ne le sont pas) :
- perdre UNE question entière fait baisser hit@5 et recall@5 de 1/26 ≈ 0,038 : REFUSÉ ;
- un bon avis qui passe du rang 1 au rang 2 sur une question fait baisser le MRR de
  0,5/26 ≈ 0,019 : TOLÉRÉ (un léger changement d'ordre n'est pas une régression).
Une tolérance nulle serait possible, car le score est reproductible (vérifié le 27/10 :
même score sur le PC et dans la CI), mais elle bloquerait le moindre changement d'ordre.

Quand une modification AMÉLIORE la recherche, on met à jour la référence dans la même
pull request (--update-reference) : la hausse devient le nouveau plancher, visible dans
le diff de eval/reference.json. C'est un « cliquet » : le niveau ne peut que monter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

GATED_METRICS = ("hit@k", "recall@k", "mrr")
DEFAULT_TOLERANCE = 0.02


@dataclass
class GateCheck:
    metric: str
    value: float
    reference: float
    threshold: float

    @property
    def ok(self) -> bool:
        return self.value >= self.threshold - 1e-9  # marge pour les arrondis


def load_reference(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_reference(summary: dict, path: str | Path, tolerance: float, note: str = "") -> dict:
    reference = {
        "date": date.today().isoformat(),
        "tolerance": tolerance,
        "scores": {m: summary["global"][m] for m in GATED_METRICS},
        "note": note,
    }
    Path(path).write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return reference


def check_gate(summary: dict, reference: dict) -> list[GateCheck]:
    tolerance = reference.get("tolerance", DEFAULT_TOLERANCE)
    return [
        GateCheck(
            metric=m,
            value=summary["global"][m],
            reference=reference["scores"][m],
            threshold=round(reference["scores"][m] - tolerance, 3),
        )
        for m in GATED_METRICS
    ]


def gate_markdown(checks: list[GateCheck], k: int) -> str:
    passed = all(c.ok for c in checks)
    title = "✅ Porte qualité : réussie" if passed else "❌ Porte qualité : ÉCHEC"
    header = "| mesure | score | référence | seuil | |"
    lines = ["", f"## {title}", "", header, "|---|---|---|---|---|"]
    for c in checks:
        name = c.metric.replace("@k", f"@{k}")
        delta = c.value - c.reference
        lines.append(
            f"| {name} | {c.value:.3f} ({delta:+.3f}) | {c.reference:.3f} | {c.threshold:.3f} "
            f"| {'✅' if c.ok else '❌'} |"
        )
    if not passed:
        lines += [
            "",
            "La recherche est moins bonne que la référence. Si la baisse est voulue (par "
            "exemple un compromis assumé), mettez à jour `eval/reference.json` avec "
            "`--update-reference` et expliquez pourquoi dans la pull request.",
        ]
    return "\n".join(lines) + "\n"
