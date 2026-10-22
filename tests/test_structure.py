"""Lots et modifications lus sans LLM (cas réels : 26-98309 Nevers, 26-98519 Maubeuge)."""

import json
from pathlib import Path

from tenderpilot.agent.graph import notice_to_dict
from tenderpilot.agent.structure import lot_lines, parse_lots, parse_modifications
from tenderpilot.ingestion.boamp import record_to_notice

FIXTURE = Path(__file__).parent / "fixtures" / "boamp_eforms_real.json"

MAUBEUGE = """Objet : Entretien et nettoyage des locaux et vitrerie
Nombre de lots : 2

Description : Le présent marché comporte deux lots : • Lot 1 : Nettoyage CTM. • Lot 2 : CMA.

Modification : La date limite d'introduction des offres a été adaptée au 09/11/26 (12.00)
Modification : Les pièces contractuelles ont été modifiées et des annexes ont été ajoutés.

Lot 1 : Nettoyage des locaux du centre technique municipal et de la Police municipale
Codes CPV : 90911000

Lot 2 : Nettoyage des locaux du Centre multi-accueil (CMA) et de la Maison Sport-Santé
Codes CPV : 90911000, 90911200
Durée : 48 mois"""


def test_lots_maubeuge():
    lots = parse_lots(MAUBEUGE)
    assert [lot["numero"] for lot in lots] == [
        "1",
        "2",
    ]  # le « • Lot 1 » en milieu de ligne est ignoré
    assert "duree" not in lots[0]
    assert lots[1]["duree"] == "48 mois"  # la durée est donnée PAR LOT
    assert lot_lines(lots)[1].endswith("Maison Sport-Santé (durée : 48 mois)")


def test_modifications_maubeuge():
    changes = parse_modifications(MAUBEUGE)
    assert len(changes) == 2
    assert changes[0].startswith("La date limite d'introduction des offres a été adaptée")


def test_fixture_reelle_nevers():
    records = json.loads(FIXTURE.read_text(encoding="utf-8"))
    records = records if isinstance(records, list) else records.get("results", records)
    notice = notice_to_dict(record_to_notice(records[0]))  # 26-98309, rectificatif, 2 lots
    assert notice["rectificatif"] is True
    assert [lot["duree"] for lot in notice["lots"]] == ["48 mois", "48 mois"]
    assert notice["lots"][0]["pme"] == "oui"
    assert notice["modifications"] == ["Report date et heure de remise des offres"]


def test_avis_sans_lot():
    assert parse_lots("Objet : X\n\nConditions du marché\nDurée : 12 mois") == []
    assert parse_modifications("Objet : X") == []
