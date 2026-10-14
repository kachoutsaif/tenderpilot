"""Affiche la structure du champ 'donnees' pour quelques avis variés."""
import json
from collections import Counter

records = json.load(open("data/sample.json", encoding="utf-8"))

def leaves(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from leaves(v, f"{path}/{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from leaves(v, path)
    elif obj not in (None, ""):
        yield path, " ".join(str(obj).split())

print("familles :", Counter(r.get("famille") for r in records))
print("natures  :", Counter(r.get("nature") for r in records))
print("etats    :", Counter(r.get("etat") for r in records))

seen = set()
for r in records:
    d = r.get("donnees")
    d = json.loads(d) if isinstance(d, str) else (d or {})
    racine = list(d.keys())[0] if d else "VIDE"
    sous = list(d[racine].keys())[0] if d and isinstance(d[racine], dict) else ""
    cle = (r.get("famille"), r.get("nature"), racine, sous)
    if cle in seen:
        continue
    seen.add(cle)
    print("\n" + "=" * 90)
    print(f"AVIS {r['idweb']} | famille={r.get('famille')} | nature={r.get('nature')} | racine={racine}/{sous}")
    print("=" * 90)
    for p, v in list(leaves(d))[:220]:
        court = "/".join(p.split("/")[-3:])
        print(f"{court[:70]:<70} | {v[:110]}")
