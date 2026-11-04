# Quais ferramentas o Terraform precisa e em qual conta ele pode mexer.

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    # Monta os zips da Lambda e do telão a partir do código do repositório.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    # Gera o sufixo dos nomes que precisam ser únicos no mundo inteiro.
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = "us-east-1"

  # A trava: se as credenciais forem de qualquer outra conta, o Terraform
  # para antes de criar, alterar ou apagar qualquer coisa.
  allowed_account_ids = [var.conta_demo]

  # Marca tudo o que for criado, para achar e conferir os custos depois.
  default_tags {
    tags = {
      Projeto = "corrida-na-nuvem"
    }
  }
}
