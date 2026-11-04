# Os valores vêm do .env, como TF_VAR_<nome>. Nenhum segredo fica no código.

variable "conta_demo" {
  description = "ID da única conta AWS em que este código pode rodar"
  type        = string

  validation {
    condition     = can(regex("^[0-9]{12}$", var.conta_demo))
    error_message = "O ID da conta precisa ter exatamente 12 dígitos."
  }
}

variable "admin_token" {
  description = "Token exigido em /admin/start e /admin/reset"
  type        = string
  sensitive   = true # não aparece na saída do plan nem do apply

  validation {
    condition     = length(var.admin_token) >= 16
    error_message = "Use um token com pelo menos 16 caracteres."
  }
}

variable "email_alerta" {
  description = "E-mail do alerta de orçamento. Vazio: o alerta não é criado."
  type        = string
  default     = ""
}
