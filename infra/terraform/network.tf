# Le réseau du projet : un VPC, UN sous-réseau public, une passerelle Internet, un pare-feu.
#
# Ce qu'on n'a PAS mis, et pourquoi (budget de démo) :
# - NAT Gateway : facturée à l'heure en continu (plus de 30 $/mois), même sans trafic ;
# - load balancer : facturé à l'heure en continu, inutile pour un seul serveur ;
# - plusieurs zones de disponibilité : utile contre les pannes en production, pas pour une
#   démo de quelques heures.
# Coûts de cette partie : VPC, sous-réseau, passerelle Internet, table de routage et
# security group sont gratuits.
#
# Analyse de sécurité (Checkov) : chaque règle ignorée l'est par un commentaire
# « checkov:skip » placé DANS la ressource, avec sa justification. Voir docs/SEMAINE_5.md.

resource "aws_vpc" "main" {
  #checkov:skip=CKV2_AWS_11:Flow logs payants (ingestion CloudWatch) ; demo de quelques heures. A activer en production.
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "tenderpilot-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "tenderpilot-igw" }
}

# Zone fixée (« a » de la région) plutôt que « la première zone disponible » : le résultat
# ne change pas si AWS ajoute une zone (règle Checkov CKV_AWS_394).
# Pas d'IP publique automatique pour tout le sous-réseau (CKV_AWS_130) : seul le serveur en
# demande une, explicitement (server.tf).
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1) # 10.20.1.0/24
  availability_zone       = "${var.region}a"
  map_public_ip_on_launch = false

  tags = { Name = "tenderpilot-public" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = { Name = "tenderpilot-public" }
}

resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}

# Le security group « par défaut » que AWS crée avec chaque VPC autorise tout le trafic
# interne. On le reprend en main SANS aucune règle : il ne laisse plus rien passer
# (CKV2_AWS_12). Une ressource créée par erreur sans pare-feu ne serait donc pas exposée.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "tenderpilot-default-ferme" }
}

# --- Le pare-feu (security group) du serveur ---
# Responsabilité partagée : AWS sécurise le réseau physique, NOUS décidons qui entre.
# Entrée : uniquement le port de l'API, uniquement depuis allowed_cidr.
# Pas de port 22 (SSH) : on se connectera par Session Manager, sans port ouvert ni clé .pem.
# (Les descriptions AWS n'acceptent que l'ASCII : pas d'accents ni d'apostrophes.)

resource "aws_security_group" "app" {
  name        = "tenderpilot-app"
  description = "TenderPilot API: one port, one IP. No SSH."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "tenderpilot-app" }
}

resource "aws_vpc_security_group_ingress_rule" "api" {
  security_group_id = aws_security_group.app.id
  description       = "API from the deployer IP only"
  cidr_ipv4         = var.allowed_cidr
  ip_protocol       = "tcp"
  from_port         = var.api_port
  to_port           = var.api_port
}

# Sortie ouverte : le serveur doit joindre l'API Groq, le registre d'images Docker,
# Parameter Store et CloudWatch. Un pare-feu filtre surtout ce qui ENTRE.
resource "aws_vpc_security_group_egress_rule" "all" {
  security_group_id = aws_security_group.app.id
  description       = "Outbound: Groq API, image registry, AWS APIs"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
}
