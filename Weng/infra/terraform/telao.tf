# Demo 2: o telão, um container Docker no Elastic Beanstalk.

# Sufixo para os nomes que precisam ser únicos fora desta conta.
resource "random_id" "sufixo" {
  byte_length = 3
}

locals {
  # A API precisa da URL do telão (CORS) e o telão precisa da URL da API.
  # Escolher o domínio do telão aqui quebra esse ciclo: ele já é conhecido
  # antes de qualquer um dos dois existir.
  dominio_telao = "corrida-telao-${random_id.sufixo.hex}"
  # Sem domínio próprio, o Beanstalk usa HTTP. A origem é exatamente esta.
  origem_telao = "http://${local.dominio_telao}.us-east-1.elasticbeanstalk.com"
}

# ------------------------------------------------------------- as permissões

# O papel da instância EC2. Precisa existir antes do ambiente.
resource "aws_iam_role" "instancia_telao" {
  name = "aws-elasticbeanstalk-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "instancia_telao" {
  role       = aws_iam_role.instancia_telao.name
  policy_arn = "arn:aws:iam::aws:policy/AWSElasticBeanstalkWebTier"
}

resource "aws_iam_instance_profile" "telao" {
  name = "aws-elasticbeanstalk-ec2-role"
  role = aws_iam_role.instancia_telao.name
}

# O papel que o próprio serviço Beanstalk usa para administrar o ambiente.
resource "aws_iam_role" "servico_beanstalk" {
  name = "aws-elasticbeanstalk-service-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "elasticbeanstalk.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "sts:ExternalId" = "elasticbeanstalk" } }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "servico_beanstalk" {
  for_each = toset([
    "arn:aws:iam::aws:policy/service-role/AWSElasticBeanstalkEnhancedHealth",
    "arn:aws:iam::aws:policy/AWSElasticBeanstalkManagedUpdatesCustomerRolePolicy",
  ])

  role       = aws_iam_role.servico_beanstalk.name
  policy_arn = each.value
}

# ---------------------------------------------------------- o pacote do telão

# O zip é feito a partir de dentro de telao/: é isso que deixa o Dockerfile na
# raiz, como o Beanstalk exige.
data "archive_file" "telao" {
  type        = "zip"
  source_dir  = "${path.module}/../../telao"
  output_path = "${path.module}/.build/telao.zip"
  excludes    = ["node_modules/**"]
}

# O prefixo "elasticbeanstalk-" não é enfeite: a política AWSElasticBeanstalkWebTier
# só libera acesso a buckets com esse começo de nome.
resource "aws_s3_bucket" "versoes" {
  bucket        = "elasticbeanstalk-corrida-${random_id.sufixo.hex}"
  force_destroy = true # o destroy apaga o bucket mesmo com zips dentro
}

resource "aws_s3_bucket_public_access_block" "versoes" {
  bucket                  = aws_s3_bucket.versoes.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "telao" {
  bucket = aws_s3_bucket.versoes.id
  key    = "telao-${data.archive_file.telao.output_md5}.zip"
  source = data.archive_file.telao.output_path
}

# ------------------------------------------------------------------ o Beanstalk

resource "aws_elastic_beanstalk_application" "telao" {
  name = "corrida-na-nuvem"
}

resource "aws_elastic_beanstalk_application_version" "telao" {
  # O nome muda junto com o código, e cada mudança vira uma versão nova.
  name        = "telao-${substr(data.archive_file.telao.output_md5, 0, 8)}"
  application = aws_elastic_beanstalk_application.telao.name
  bucket      = aws_s3_bucket.versoes.id
  key         = aws_s3_object.telao.key

  # A versão nova entra no ar antes de a antiga ser apagada.
  lifecycle {
    create_before_destroy = true
  }
}

# Sempre a plataforma Docker mais recente em Amazon Linux 2023.
data "aws_elastic_beanstalk_solution_stack" "docker" {
  most_recent = true
  name_regex  = "^64bit Amazon Linux 2023 (.*) running Docker$"
}

resource "aws_elastic_beanstalk_environment" "telao" {
  name                = "corrida-telao"
  application         = aws_elastic_beanstalk_application.telao.name
  solution_stack_name = data.aws_elastic_beanstalk_solution_stack.docker.name
  version_label       = aws_elastic_beanstalk_application_version.telao.name
  cname_prefix        = local.dominio_telao

  # Instância única: sem load balancer, bem mais barato para uma demo.
  setting {
    namespace = "aws:elasticbeanstalk:environment"
    name      = "EnvironmentType"
    value     = "SingleInstance"
  }
  setting {
    namespace = "aws:elasticbeanstalk:environment"
    name      = "ServiceRole"
    value     = aws_iam_role.servico_beanstalk.name
  }
  setting {
    namespace = "aws:ec2:instances"
    name      = "InstanceTypes"
    value     = "t3.micro"
  }
  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "IamInstanceProfile"
    value     = aws_iam_instance_profile.telao.name
  }

  # Contas novas não podem usar launch configurations. Estas duas opções fazem
  # o Beanstalk usar launch template, e a primeira ainda melhora a segurança.
  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "DisableIMDSv1"
    value     = "true"
  }
  setting {
    namespace = "aws:autoscaling:launchconfiguration"
    name      = "RootVolumeType"
    value     = "gp3"
  }

  setting {
    namespace = "aws:elasticbeanstalk:healthreporting:system"
    name      = "SystemType"
    value     = "enhanced"
  }

  # É aqui que a URL da API chega ao container. O token de admin nunca passa
  # por aqui: o telão é público e pede o token na própria tela.
  setting {
    namespace = "aws:elasticbeanstalk:application:environment"
    name      = "API_URL"
    value     = aws_apigatewayv2_stage.padrao.invoke_url
  }

  # O ambiente só pode nascer com as permissões prontas.
  depends_on = [
    aws_iam_role_policy_attachment.instancia_telao,
    aws_iam_role_policy_attachment.servico_beanstalk,
  ]
}
