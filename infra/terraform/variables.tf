# Les paramètres du déploiement. Leurs valeurs vont dans terraform.tfvars (ignoré par git),
# jamais dans le code : l'adresse IP de la personne qui déploie n'a rien à faire sur GitHub.

variable "region" {
  description = "Région AWS. eu-west-3 = Paris (données en France, faible latence)."
  type        = string
  default     = "eu-west-3"
}

variable "allowed_cidr" {
  description = "La SEULE adresse autorisée à appeler l'API, au format x.x.x.x/32 (votre IP)."
  type        = string

  validation {
    # Garde-fou : refuse 0.0.0.0/0 (« le monde entier ») et toute plage plus large qu'une IP.
    condition     = can(cidrhost(var.allowed_cidr, 0)) && endswith(var.allowed_cidr, "/32")
    error_message = "allowed_cidr doit être UNE adresse IP au format x.x.x.x/32 (jamais 0.0.0.0/0)."
  }
}

variable "vpc_cidr" {
  description = "Plage d'adresses privées du réseau du projet."
  type        = string
  default     = "10.20.0.0/16"
}

variable "api_port" {
  description = "Port de l'API TenderPilot (uvicorn)."
  type        = number
  default     = 8000
}
