# Le garde-fou financier : un e-mail AVANT que la facture ne surprenne.
# Les deux premiers budgets AWS sont gratuits.
#   - à 50 % du budget RÉELLEMENT dépensé ;
#   - quand la PRÉVISION du mois dépasse 100 % (AWS extrapole la consommation actuelle).
# Après création, AWS envoie un e-mail de confirmation : il faut cliquer sur le lien.

resource "aws_budgets_budget" "monthly" {
  name         = "tenderpilot-mensuel"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_limit_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
