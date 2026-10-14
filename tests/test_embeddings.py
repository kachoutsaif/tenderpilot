from tenderpilot.rag.embeddings import normalize_case


def test_texte_crie_mis_en_minuscules():
    assert normalize_case("NETTOYAGE DE VITRES, DE L'ENCADREMENT") == (
        "nettoyage de vitres, de l'encadrement"
    )


def test_sigles_isoles_conserves():
    assert normalize_case("Accord-cadre de VRD pour la CAIH") == "Accord-cadre de VRD pour la CAIH"


def test_mot_long_isole_mis_en_minuscules():
    assert normalize_case("Marché du SMICVAL") == "Marché du smicval"


def test_texte_mixte():
    text = "Infrastructure VPN pour les UFA du CFA AGRICOLE PUBLIC DES HAUTS-DE-FRANCE"
    assert normalize_case(text) == (
        "Infrastructure VPN pour les UFA du cfa agricole public des hauts-de-france"
    )


def test_texte_normal_inchange():
    text = "Travaux de marquage routier, Mairie de Cernay, Département : 68"
    assert normalize_case(text) == text
