# Les secrets, rangés dans Parameter Store (SecureString = chiffrés par AWS KMS).
# Niveau « standard » : gratuit.
#
# 1) Mot de passe PostgreSQL : généré par Terraform, jamais tapé ni affiché.
#    Il est aussi écrit dans l'ÉTAT Terraform : une raison de plus pour que terraform.tfstate
#    ne quitte jamais votre PC (.gitignore).
#
# 2) Clé Groq : Terraform crée seulement l'EMPLACEMENT, avec une valeur factice. Vous mettez
#    la vraie clé ensuite, avec la commande AWS CLI donnée dans les sorties. Ainsi la clé ne
#    passe JAMAIS par Terraform : ni dans un fichier .tfvars, ni dans l'état.

resource "random_password" "db" {
  length  = 32
  special = false # elle sert dans une URL postgresql://... : pas de caractères spéciaux
}

resource "aws_ssm_parameter" "db_password" {
  name        = "/tenderpilot/db_password"
  description = "Mot de passe PostgreSQL de TenderPilot"
  type        = "SecureString"
  value       = random_password.db.result
}

resource "aws_ssm_parameter" "llm_api_key" {
  name        = "/tenderpilot/llm_api_key"
  description = "Cle API Groq (a definir avec aws ssm put-parameter --overwrite)"
  type        = "SecureString"
  value       = "A_REMPLACER"

  lifecycle {
    # Terraform ne remet pas la valeur factice si vous avez mis la vraie clé.
    ignore_changes = [value]
  }
}
