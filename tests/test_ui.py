"""Interface web : servie telle quelle, sans faille d'injection évidente."""

from tenderpilot.api.ui import UI_HTML


def test_page_complete():
    assert UI_HTML.startswith("<!DOCTYPE html>")
    assert 'fetch("/ask"' in UI_HTML and "<title>TenderPilot</title>" in UI_HTML


def test_texte_externe_jamais_insere_comme_html():
    # Réponses du LLM et extraits d'avis : du texte venu de l'extérieur.
    assert "innerHTML" not in UI_HTML
    assert "textContent" in UI_HTML
    assert "safeUrl" in UI_HTML  # liens limités à http(s) : pas de javascript:...
