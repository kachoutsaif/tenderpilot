# Versions de Terraform et du fournisseur AWS.
# On fixe une plage de versions : une mise à jour majeure du fournisseur (7.x) pourrait
# changer le comportement des ressources sans prévenir. Même logique que la porte qualité :
# un résultat ne doit pas changer sans qu'on l'ait décidé.

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }
}

provider "aws" {
  region = var.region

  # Étiquettes posées sur TOUTES les ressources : dans la console et sur la facture AWS,
  # on retrouve en un filtre tout ce qui appartient au projet (et ce qu'il coûte).
  default_tags {
    tags = {
      Project   = "tenderpilot"
      ManagedBy = "terraform"
    }
  }
}
