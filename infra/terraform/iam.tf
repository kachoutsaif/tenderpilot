# Le rôle du serveur : ce que le serveur a le droit de faire chez AWS.
# Principe du MOINDRE PRIVILÈGE : exactement ce dont il a besoin, rien de plus.
#
#   - lire NOS DEUX paramètres (pas tous ceux du compte) ;
#   - écrire dans NOTRE groupe de journaux (pas dans les autres) ;
#   - accepter Session Manager (politique gérée par AWS), pour se connecter sans SSH.
#
# Pas de clé d'accès sur le serveur : le rôle lui donne des identifiants temporaires,
# renouvelés automatiquement par AWS. Rien à voler sur le disque.

data "aws_iam_policy_document" "assume_ec2" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "server" {
  name               = "tenderpilot-server"
  assume_role_policy = data.aws_iam_policy_document.assume_ec2.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.server.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "server" {
  statement {
    sid     = "LireNosSecrets"
    actions = ["ssm:GetParameter"]
    resources = [
      aws_ssm_parameter.db_password.arn,
      aws_ssm_parameter.llm_api_key.arn,
    ]
  }

  statement {
    sid       = "EcrireNosJournaux"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "server" {
  name   = "tenderpilot-server"
  role   = aws_iam_role.server.id
  policy = data.aws_iam_policy_document.server.json
}

resource "aws_iam_instance_profile" "server" {
  name = "tenderpilot-server"
  role = aws_iam_role.server.name
}
