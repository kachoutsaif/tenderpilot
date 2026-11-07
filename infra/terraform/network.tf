# Le réseau du projet : un VPC, UN sous-réseau public, une passerelle Internet, un pare-feu.
#
# Ce qu'on n'a PAS mis, et pourquoi (budget de démo) :
# - NAT Gateway : facturée à l'heure en continu (plus de 30 $/mois), même sans trafic ;
# - load balancer : facturé à l'heure en continu, inutile pour un seul serveur ;
# - plusieurs zones de disponibilité : utile contre les pannes en production, pas pour une
#   démo de quelques heures.
# Coûts de cette partie : VPC, sous-réseau, passerelle Internet, table de routage et
# security group sont gratuits.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "tenderpilot-vpc" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = { Name = "tenderpilot-igw" }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, 1) # 10.20.1.0/24
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true # adresse IPv4 publique : facturée à l'heure, voir docs

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
