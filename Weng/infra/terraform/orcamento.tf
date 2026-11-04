# Alerta por e-mail quando o gasto real do mês passar de 80% de US$ 5.
# Ele só avisa, não impede gastos, e os dados de custo chegam com horas de atraso.
# A proteção de verdade é o terraform destroy depois da palestra.

resource "aws_budgets_budget" "alerta" {
  count = var.email_alerta == "" ? 0 : 1

  name         = "corrida-na-nuvem"
  budget_type  = "COST"
  limit_amount = "5"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.email_alerta]
  }
}
