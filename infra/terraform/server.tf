# Le serveur : une machine EC2 qui fait tourner PostgreSQL et l'API dans Docker.

# Image système : la dernière Amazon Linux 2023, lue dans un paramètre public d'AWS.
# Elle contient déjà l'agent Session Manager et l'AWS CLI.
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# Journaux : nos lignes JSON « appel_outil » de la semaine 4 arriveront ici.
# Conservation 7 jours : assez pour une démo, et le stockage reste quasi gratuit.
resource "aws_cloudwatch_log_group" "app" {
  name              = "/tenderpilot/app"
  retention_in_days = 7
}

resource "aws_instance" "server" {
  ami                    = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile   = aws_iam_instance_profile.server.name

  root_block_device {
    volume_type = "gp3"
    volume_size = 20   # Go : système + images Docker + données PostgreSQL
    encrypted   = true # chiffrement du disque, sans surcoût
  }

  # IMDSv2 obligatoire : protège les identifiants temporaires du rôle contre une attaque
  # classique (une requête forgée qui interroge le service de métadonnées).
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region            = var.region
    app_image         = var.app_image
    api_port          = var.api_port
    log_group         = aws_cloudwatch_log_group.app.name
    db_password_param = aws_ssm_parameter.db_password.name
    llm_key_param     = aws_ssm_parameter.llm_api_key.name
  })
  # Le script ne s'exécute qu'au premier démarrage : s'il change, on recrée le serveur.
  user_data_replace_on_change = true

  tags = { Name = "tenderpilot-server" }
}
