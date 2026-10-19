"""Agent de qualification d'un appel d'offres (semaine 3).

Principe : le LLM LIT (extraction des exigences, rédaction), des règles en Python
DÉCIDENT (GO / À ÉTUDIER / NO-GO), et un humain VALIDE avant toute rédaction.
L'agent traite un seul avis à la fois, ce qui évite de mélanger les informations
de plusieurs avis (erreur d'attribution observée en semaine 2).
"""
