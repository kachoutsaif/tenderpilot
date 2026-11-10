# Semaine 5 : déploiement sur AWS avec Terraform

**Objectif :** décrire toute l'infrastructure en code, la créer en une commande pour une démo,
puis la détruire en une commande. Sous contrainte de budget.

| Étape | Contenu | Compte AWS ? | État |
|---|---|---|---|
| 1 | Installer Terraform, choisir l'architecture | non | fait |
| 2 | Code Terraform : réseau, pare-feu, serveur, rôle, secrets, budget | non | fait |
| 3 | Vérifier le code Terraform dans la CI (fmt, validate, Checkov) | non | fait |
| 4 | Construire l'image Docker dans GitHub Actions (ghcr.io) | non | à faire |
| 5 | Déployer, démontrer, mesurer, `terraform destroy` | oui | à faire |

## Accès AWS

Le Learner Lab AWS Academy de l'école (50 $) est clos ; une demande de réouverture est en
cours. Solution de repli : compte personnel en **Free plan** (crédits jusqu'à 200 $, 6 mois,
aucun frais au-delà des crédits : le compte se ferme). Le code est identique dans les deux
cas, à une différence près : le Learner Lab interdit de créer des rôles IAM (il faudrait
réutiliser `LabRole` au lieu de `iam.tf`).

## Architecture

```
Internet (votre IP seulement) ──► port 8000
  VPC 10.20.0.0/16 ─ sous-réseau public 10.20.1.0/24
    EC2 t3.small (Amazon Linux 2023), disque 20 Go chiffré
      Docker : [ API TenderPilot ] ──réseau Docker──► [ PostgreSQL + pgvector ]
  Parameter Store : mot de passe PostgreSQL, clé Groq (chiffrés)
  CloudWatch Logs : journaux des conteneurs, 7 jours
  Budget : e-mail à 50 % dépensés et à 100 % prévus
```

| Besoin | Choix | Évité, et pourquoi |
|---|---|---|
| Calcul | 1 EC2 + Docker | ECS / EKS : plus complexes et plus chers pour une démo |
| Base | PostgreSQL dans Docker | RDS : facturé en continu, même inutilisé |
| Réseau | sous-réseau public, port API ouvert à UNE IP | NAT Gateway (> 30 $/mois), load balancer |
| Administration | Session Manager | SSH ouvert, clé .pem à protéger |
| Secrets | Parameter Store SecureString (gratuit) | clé dans le code, les .tfvars ou l'état Terraform |
| Garde-fou | budget AWS + `terraform destroy` | découvrir la facture en fin de mois |

**En production**, on changerait : RDS (sauvegardes, haute disponibilité), sous-réseaux privés
+ load balancer + HTTPS, plusieurs zones, état Terraform dans S3 avec verrou.

## Sécurité : ce que montre le code

- **Moindre privilège** (`iam.tf`) : le serveur lit DEUX paramètres et écrit dans UN groupe
  de journaux ; rien d'autre. Aucune clé d'accès sur le disque (rôle = identifiants temporaires).
- **Pare-feu** (`network.tf`) : une seule entrée, le port de l'API, depuis une seule IP ;
  `variables.tf` refuse `0.0.0.0/0`. PostgreSQL n'a aucun port publié.
- **IMDSv2 obligatoire**, disque chiffré.
- **La clé Groq ne passe jamais par Terraform** : Terraform crée l'emplacement avec une valeur
  factice (`ignore_changes`), la vraie clé est posée ensuite avec l'AWS CLI. Elle n'apparaît
  donc ni dans un fichier `.tfvars`, ni dans `terraform.tfstate`.
- **Jamais dans git** : `.terraform/`, `*.tfstate` (il contient le mot de passe PostgreSQL),
  `*.tfvars`. Dans git : `.terraform.lock.hcl` (versions exactes des fournisseurs).

## Coût estimé d'une démo de 3 heures (région Paris, ordre de grandeur)

EC2 t3.small quelques centimes de l'heure, adresse IPv4 publique ~0,005 $/h, disque 20 Go
facturé au prorata ; VPC, security group, Parameter Store standard, budget : gratuits.
Total : de l'ordre de 0,10 $. À vérifier après la démo dans Billing → Cost Explorer.

## Étape 3 : analyse de sécurité de l'infrastructure (Checkov)

Checkov compare les fichiers `.tf` à plusieurs centaines de règles de bonnes pratiques AWS,
sans compte AWS. Premier passage (7/11) : **56 règles respectées, 10 non respectées**.
Méthode : mesurer, comprendre chaque alerte, puis corriger si c'est gratuit et utile, ou
ignorer avec une justification écrite **dans la ressource** (`#checkov:skip=...`).

| Règle | Ce qu'elle demande | Décision |
|---|---|---|
| CKV_AWS_394 | zone de disponibilité fixe | **corrigé** : zone `<région>a`, plus de source « première zone disponible » |
| CKV_AWS_130 | pas d'IP publique automatique dans le sous-réseau | **corrigé** : seul le serveur demande une IP, explicitement |
| CKV_AWS_135 | disque EBS optimisé | **corrigé** : gratuit sur les t3 |
| CKV2_AWS_12 | security group par défaut fermé | **corrigé** : repris en main sans aucune règle |
| CKV_AWS_337 (×2) | clé KMS dédiée pour Parameter Store | ignoré : déjà chiffré par la clé gérée AWS ; clé dédiée ≈ 1 $/mois |
| CKV_AWS_158 | clé KMS dédiée pour les journaux | ignoré : déjà chiffrés au repos ; même coût |
| CKV_AWS_338 | journaux conservés 1 an | ignoré : 7 jours pour une démo, et garder moins = minimiser les données |
| CKV_AWS_126 | surveillance détaillée (1 minute) | ignoré : payante ; 5 minutes suffisent |
| CKV2_AWS_11 | journaux de flux réseau (flow logs) | ignoré : payants ; à activer en production |

Bilan : **4 corrections gratuites, 6 exceptions justifiées** (toutes par le coût, pour une
démo). Ce qui compte n'est pas « zéro alerte » mais une décision écrite pour chacune.

La CI (`.github/workflows/infra.yml`) lance à chaque pull request `terraform fmt -check`,
`terraform validate` et Checkov, avec des versions fixées (Terraform 1.17.1, Checkov 3.4.3) :
une nouvelle règle Checkov ne doit pas faire échouer la CI sans que le code ait changé.
Une nouvelle alerte sur une PR signale donc une régression de sécurité de l'infrastructure.
