"""Profil de l'entreprise qui répond aux appels d'offres (fichier TOML lisible et modifiable)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


class Reference(BaseModel):
    titre: str
    annee: int | None = None
    montant: float | None = None


class CompanyProfile(BaseModel):
    nom: str
    description: str = ""
    activites: list[str] = Field(min_length=1)
    departements: list[str] = Field(default_factory=list)  # vide = toute la France
    chiffre_affaires: float | None = None
    effectif: int | None = None
    certifications: list[str] = Field(default_factory=list)
    delai_minimum_jours: int = 10
    references: list[Reference] = Field(default_factory=list)


def load_profile(path: str | Path) -> CompanyProfile:
    with open(path, "rb") as f:
        return CompanyProfile.model_validate(tomllib.load(f))
