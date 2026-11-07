# Valeurs affichées après « terraform apply » (et lisibles par « terraform output »).

output "vpc_id" {
  value = aws_vpc.main.id
}

output "public_subnet_id" {
  value = aws_subnet.public.id
}

output "security_group_id" {
  value = aws_security_group.app.id
}

output "instance_id" {
  value = aws_instance.server.id
}

output "api_url" {
  description = "Adresse de l'API (accessible depuis votre IP seulement)."
  value       = "http://${aws_instance.server.public_ip}:${var.api_port}"
}

output "se_connecter" {
  description = "Ouvrir un terminal sur le serveur, sans SSH."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.server.id}"
}

output "definir_cle_groq" {
  description = "À lancer une fois après apply (la clé ne passe jamais par Terraform)."
  value       = "aws ssm put-parameter --region ${var.region} --name ${aws_ssm_parameter.llm_api_key.name} --type SecureString --overwrite --value \"$LLM_API_KEY\""
}
