# O que o terraform apply mostra no final.

output "url_jogador" {
  description = "Página do celular; é o endereço que vira QR no telão"
  value       = aws_apigatewayv2_stage.padrao.invoke_url
}

output "url_telao" {
  description = "Placar para abrir no projetor"
  value       = "http://${aws_elastic_beanstalk_environment.telao.cname}"
}
