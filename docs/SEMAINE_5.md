# Semaine 5 : déploiement sur AWS avec Terraform

**Objectif :** décrire toute l'infrastructure en code, la créer en une commande pour une démo,
puis la détruire en une commande. Sous contrainte de budget.

| Étape | Contenu | Compte AWS ? | État |
|---|---|---|---|
| 1 | Installer Terraform, choisir l'architecture | non | fait |
| 2 | Code Terraform : réseau, pare-feu, serveur, rôle, secrets, budget | non | en cours |
| 3 | Vérifier le code Terraform dans la CI | non | à faire |
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
