# Demo 1: API Gateway (HTTP API) -> Lambda -> DynamoDB e Bedrock.

# ------------------------------------------------------------------ o placar

resource "aws_dynamodb_table" "placar" {
  name         = "corrida-na-nuvem"
  billing_mode = "PAY_PER_REQUEST" # on-demand: paga por escrita, sem capacidade fixa
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }
}

# ------------------------------------------------------- a permissão da Lambda

resource "aws_iam_role" "lambda" {
  name = "corrida-na-nuvem-lambda"

  # Só o serviço Lambda pode assumir este papel.
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Privilégio mínimo: cada ação lista exatamente o recurso em que pode agir.
# Nada de "Action": "*".
resource "aws_iam_role_policy" "lambda" {
  name = "corrida-na-nuvem-minimo"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PlacarNoDynamoDB"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.placar.arn
      },
      {
        # A API Converse usa a permissão bedrock:InvokeModel.
        Sid      = "LocutorNoBedrock"
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0"
      },
      {
        Sid      = "LogsNoCloudWatch"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.lambda.arn}:*"
      },
    ]
  })
}

# ------------------------------------------------------------------ a Lambda

# Criado aqui para sumir no destroy e não acumular logs para sempre.
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/corrida-na-nuvem"
  retention_in_days = 7
}

# Só os dois arquivos que a Lambda usa. Os testes ficam de fora.
data "archive_file" "lambda" {
  type        = "zip"
  output_path = "${path.module}/.build/api.zip"

  source {
    content  = file("${path.module}/../../api/lambda_function.py")
    filename = "lambda_function.py"
  }
  source {
    content  = file("${path.module}/../../api/player.html")
    filename = "player.html"
  }
}

resource "aws_lambda_function" "api" {
  function_name = "corrida-na-nuvem"
  role          = aws_iam_role.lambda.arn
  runtime       = "python3.13"
  handler       = "lambda_function.lambda_handler"
  timeout       = 10
  memory_size   = 256

  filename = data.archive_file.lambda.output_path
  # Se o código mudar, o hash muda e o Terraform publica a versão nova.
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = {
      TABLE_NAME  = aws_dynamodb_table.placar.name
      ADMIN_TOKEN = var.admin_token
    }
  }

  # O grupo de logs precisa existir antes, para a Lambda não tentar criá-lo.
  depends_on = [aws_cloudwatch_log_group.lambda]
}

# ---------------------------------------------------------------- o API Gateway

resource "aws_apigatewayv2_api" "api" {
  name          = "corrida-api"
  protocol_type = "HTTP"

  # O API Gateway responde o preflight (OPTIONS) sozinho e ignora headers de
  # CORS vindos da Lambda. A página do jogador tem a mesma origem da API, então
  # o navegador não aplica CORS a ela: só o telão precisa estar na lista.
  cors_configuration {
    allow_origins = [local.origem_telao]
    allow_methods = ["GET", "POST"]
    allow_headers = ["x-admin-token"]
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# As cinco rotas apontam para a mesma Lambda, que decide por método e caminho.
resource "aws_apigatewayv2_route" "rotas" {
  for_each = toset([
    "GET /",
    "POST /tap",
    "GET /state",
    "POST /admin/start",
    "POST /admin/reset",
  ])

  api_id    = aws_apigatewayv2_api.api.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

# O stage $default deixa as URLs sem prefixo, como o código espera.
resource "aws_apigatewayv2_stage" "padrao" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
}

# Sem esta permissão, o API Gateway não consegue invocar a Lambda.
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "PermitirApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
