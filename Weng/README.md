# Corrida na Nuvem

Demo ao vivo da palestra "Construindo na AWS". A sala abre um QR no celular, escolhe uma Região e
toca o botão por 60 segundos. O telão mostra a corrida ao vivo, um locutor gerado pelo Amazon
Bedrock, o vencedor e o custo estimado da rodada.

```
Celulares ──┐
            ├─► API Gateway (HTTP API) ─► Lambda (Python 3.13) ─┬─► DynamoDB (on-demand)
Telão ──────┘                                                   └─► Bedrock (Nova Micro)
  ▲
  └── página servida por um container Docker no Elastic Beanstalk
```

Tudo fica em `us-east-1`. ECS/Fargate aparecem só nos slides.

## Por que aguenta a sala

| Regra | Efeito |
| --- | --- |
| O celular junta os toques e envia no máximo 1 `POST /tap` por segundo | 100 pessoas são cerca de 100 req/s, não 600 |
| `ADD` atômico em uma única escrita, sem ler antes | Nenhum toque se perde com escritas simultâneas |
| Atraso aleatório no início de cada celular | As requisições se espalham ao longo do segundo |
| Bedrock só no `GET /state`, com escrita condicional | No máximo uma frase a cada 10 s, com qualquer número de chamadas |
| Falha de rede ou 5xx: os toques ficam guardados no celular | O próximo envio leva o acumulado |

Bom gancho para a palestra: o jogo inteiro mora em **um único item**, e cada partição do DynamoDB
foi projetada para até 1.000 unidades de escrita por segundo. Com 100 pessoas enviando uma vez por
segundo, usamos cerca de 10% disso. Com uma requisição por toque, passaríamos de 60% e a conta
ficaria seis vezes maior.

## Estrutura

```
api/lambda_function.py      handler único, com as 5 rotas
api/player.html             página do celular (vai no zip da Lambda)
api/tests/test_handler.py   testes com moto (DynamoDB) e Stubber (Bedrock)
telao/                      Node 20 + Express em Docker; public/ tem o placar em tema RPG e os heróis
infra/terraform/            Terraform: toda a infraestrutura como código
infra/template.yaml         AWS SAM: só a API, como plano B
scripts/conta-demo.sh       roda um comando usando só a conta de demo do .env
scripts/empacotar.sh        gera dist/api.zip e dist/telao.zip
scripts/carga.py            teste de carga da véspera
docs/roteiro-ao-vivo.md     cliques no console, plano B e checklist
```

## Testes locais (grátis, não falam com a AWS)

```bash
python3.13 -m venv .venv
```

```bash
.venv/bin/pip install -r api/requirements-dev.txt
```

```bash
.venv/bin/python -m pytest api/tests -q
```

## Gerar os zips

```bash
./scripts/empacotar.sh
```

O script confere que o `Dockerfile` está na raiz de `dist/telao.zip`, como o Beanstalk exige.

## Deploy

### Terraform (caminho principal)

Cria tudo: tabela, Lambda, API, telão no Beanstalk, permissões e alerta de orçamento, com os mesmos
nomes usados no roteiro.

**Conta isolada.** Todo comando passa por `scripts/conta-demo.sh`, que lê as credenciais só do
`.env`, ignora as variáveis AWS do terminal e não altera `~/.aws`. Com chaves no `.env`, ele esconde
`~/.aws` do comando; com `AWS_PROFILE`, recusa o perfil `default`. Além disso,
`allowed_account_ids` faz o Terraform parar se a conta não for a informada em `TF_VAR_conta_demo`.

```bash
cp .env.example .env
```

Preencha o `.env` e rode:

```bash
scripts/conta-demo.sh aws sts get-caller-identity
```

```bash
scripts/conta-demo.sh terraform -chdir=infra/terraform init
```

```bash
scripts/conta-demo.sh terraform -chdir=infra/terraform plan
```

```bash
scripts/conta-demo.sh terraform -chdir=infra/terraform apply
```

A criação do ambiente Beanstalk leva alguns minutos. No final, `url_jogador` e `url_telao` aparecem
na saída.

- **O estado fica em `infra/terraform/terraform.tfstate` e guarda o `ADMIN_TOKEN` em texto puro.**
  Ele nunca vai para o git, e sem ele o `destroy` não funciona: não apague esse arquivo antes de
  destruir tudo.
- **O domínio do telão é escolhido antes da criação**, e é isso que resolve o ciclo entre o CORS da
  API e o `API_URL` do telão.
- **Mudanças feitas no console são desfeitas pelo próximo `apply`.** O deploy ao vivo de uma versão
  nova pelo console, por exemplo, volta para a versão do repositório.

### Console

Para fazer tudo à mão, siga a preparação em [docs/roteiro-ao-vivo.md](docs/roteiro-ao-vivo.md).

### Plano B: AWS SAM

Cria tabela, Lambda, API e permissões de uma vez. Os nomes não colidem com os recursos criados no
console nem pelo Terraform.

```bash
./scripts/empacotar.sh
```

```bash
export ADMIN_TOKEN="$(openssl rand -hex 24)"
```

```bash
sam deploy --template-file infra/template.yaml --stack-name corrida-sam --region us-east-1 --resolve-s3 --capabilities CAPABILITY_IAM --parameter-overrides "AdminToken=$ADMIN_TOKEN TelaoOrigin=http://localhost:8080"
```

A saída `ApiUrl` é o valor de `API_URL` do telão. Depois que o Beanstalk tiver URL, repita o
`sam deploy` com `TelaoOrigin=http://SEU-AMBIENTE.us-east-1.elasticbeanstalk.com`.

> Não use `--guided` nem `--save-params`: eles gravariam o token em `samconfig.toml`.

### Sobre o CORS

- Fica configurado no API Gateway, que responde o preflight sozinho e **ignora** headers de CORS
  vindos da Lambda. Por isso a Lambda não envia nenhum.
- O Beanstalk sem domínio próprio usa HTTP. A origem é `http://...`, sem barra no final.
- A página do jogador vem do próprio API Gateway e chama a mesma origem, então o navegador não
  aplica CORS a ela. Só o telão precisa estar na lista.

## Telão em tema RPG

Cada Região é um herói de pixel art (`telao/public/herois.js`) que corre sobre a própria barra. Os
toques do último segundo saltam como números de dano, o locutor fala em uma caixa de diálogo, só em
texto, e o custo aparece como ouro gasto.

As fontes vêm do Google Fonts e o QR, do cdnjs. Se a rede do local bloquear esses endereços, o placar
continua funcionando com uma fonte comum, e o endereço do jogador continua escrito na tela.

## Segurança

- O papel da Lambda só tem `dynamodb:GetItem` e `dynamodb:UpdateItem` na tabela da demo,
  `bedrock:InvokeModel` no ARN do Nova Micro e escrita de logs. Nenhum `"Action": "*"`.
- `ADMIN_TOKEN` vem de variável de ambiente. Sem ela, as rotas de admin recusam todo mundo.
- O token nunca chega ao HTML do telão, que é público: você digita em um campo de senha, antes de
  projetar, e ele fica só no `sessionStorage` daquela aba.
- **Não abra a aba de variáveis de ambiente da Lambda com o projetor ligado.** O token aparece em
  texto puro.

## Custo

| Item | Estimativa |
| --- | --- |
| Uma rodada com 100 pessoas (cerca de 6.000 requisições) | cerca de US$ 0,012, sem o nível gratuito |
| Frases do locutor (cerca de 5 por rodada, até 60 tokens de saída cada) | frações de centavo |
| Beanstalk em `t3.micro`, instância única | custo por hora enquanto estiver no ar: é o que pesa se ficar esquecido |

O telão calcula a primeira linha a partir de `requests`. Os preços ficam em constantes no topo de
[telao/public/index.html](telao/public/index.html), com a data e a fonte. O cálculo não inclui
Beanstalk nem Bedrock, e o telão deixa claro quais serviços entram.

## Alerta do AWS Budgets

Faça isso antes de criar qualquer recurso. **O alerta avisa, mas não impede gastos**, e os dados de
custo têm atraso de horas. A proteção real é apagar tudo depois da palestra.

Terraform: preencha `TF_VAR_email_alerta` no `.env` e o alerta é criado junto com o resto.

Console: **Billing and Cost Management → Budgets → Create budget → Customize → Cost budget**, valor
mensal de US$ 5, alerta em 80% do custo real, com o seu e-mail.

Ou pela CLI, trocando `<CONTA>` e `<SEU_EMAIL>`:

```bash
aws budgets create-budget --account-id <CONTA> --budget '{"BudgetName":"corrida-na-nuvem","BudgetLimit":{"Amount":"5","Unit":"USD"},"TimeUnit":"MONTHLY","BudgetType":"COST"}' --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"GREATER_THAN","Threshold":80,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"<SEU_EMAIL>"}]}]'
```

## Apagar tudo depois da palestra

Faça no mesmo dia, em `us-east-1`.

**Se você usou o Terraform**, um comando apaga tudo o que ele criou, inclusive o alerta de orçamento:

```bash
scripts/conta-demo.sh terraform -chdir=infra/terraform destroy
```

Depois, siga só os passos 4 e 5 abaixo: o Beanstalk cria sozinho o bucket
`elasticbeanstalk-us-east-1-<CONTA>`, que o Terraform não conhece. Se quiser manter o alerta até a
próxima fatura, recrie-o pelo console.

**Se você criou no console ou pelo SAM**, siga esta ordem:

**1. Telão (é o que custa por hora)**

```bash
aws elasticbeanstalk terminate-environment --environment-name corrida-telao --region us-east-1
```

Espere o ambiente sumir do console (alguns minutos) e apague a aplicação:

```bash
aws elasticbeanstalk delete-application --application-name corrida-na-nuvem --region us-east-1
```

**2. API, se você criou no console**

- API Gateway: apague a API `corrida-api`.
- Lambda: apague a função `corrida-na-nuvem`.
- DynamoDB: apague a tabela `corrida-na-nuvem`.
- CloudWatch Logs: apague `/aws/lambda/corrida-na-nuvem` e qualquer `/aws/elasticbeanstalk/*` da demo.
- IAM: apague o papel `corrida-na-nuvem-lambda`.

**3. API, se você usou o SAM**

```bash
sam delete --stack-name corrida-sam --region us-east-1
```

Se aparecer `aws-sam-cli-managed-default` no CloudFormation e nenhum outro projeto usar, esvazie o
bucket dessa stack e apague a stack também.

**4. Restos do Beanstalk**

- S3: o bucket `elasticbeanstalk-us-east-1-<CONTA>` guarda os zips e tem uma política que impede a
  exclusão. **Ele é compartilhado por todos os ambientes Beanstalk da região:** só apague se não
  houver outro projeto. Remova a política do bucket, esvazie e apague.
- IAM: apague `aws-elasticbeanstalk-ec2-role` e `aws-elasticbeanstalk-service-role`, se nada mais
  usar.

**5. Conferir**

- EC2: nenhuma instância, volume ou Elastic IP sobrando.
- No dia seguinte, veja o Cost Explorer. Mantenha o alerta de orçamento até a próxima fatura e só
  então apague.

## Roteiro do dia

Passo a passo, tempos, plano B e checklist da véspera:
[docs/roteiro-ao-vivo.md](docs/roteiro-ao-vivo.md).

| Passo | Tempo |
| --- | --- |
| 1. Mostrar a tabela do DynamoDB vazia | 1 min |
| 2. Mostrar a Lambda e as rotas; abrir a URL no celular | 4 min |
| 3. Mostrar o telão no Beanstalk e o deploy de uma nova versão | 3 min |
| 4. Rodar 2 ou 3 rodadas com a sala | 6 a 8 min |
| 5. Abrir o CloudWatch: invocações e duração no pico | 3 min |
| 6. Mostrar a estimativa de custo | 1 min |

## Decisões que a especificação deixou em aberto

- **Frases de reserva, por decisão posterior à especificação original**: se o Bedrock falhar, a
  Lambda usa uma frase pronta com o placar real, em vez de manter a anterior. O campo `phraseSource`
  e o nome "Locutor de reserva" no telão deixam claro que a frase não veio do modelo, e o Bedrock
  volta sozinho quando responder.
- **O celular também consulta `GET /state`**, a cada 2 s e só fora da corrida, para descobrir a
  largada e mostrar os avisos. Durante a corrida, a resposta do `/tap` traz o tempo restante.
- **`requests` conta `/tap` e `/state` só durante a rodada**, para o total e o custo não subirem
  depois do fim. O CloudWatch sempre mostrará mais invocações, porque inclui a página e as consultas
  fora da rodada.
- **Largada também zera o placar**, para não misturar rodadas se você esquecer o Zerar. Largada com
  rodada em andamento devolve 409, então um clique duplo não apaga nada.
- **`/tap` fora da rodada devolve 409**, e não 400: o pedido é válido, a rodada é que não está ativa.
- **Dockerfile usa o espelho `public.ecr.aws`** da imagem oficial do Node, para evitar o limite de
  downloads anônimos do Docker Hub durante o deploy.
- **`scripts/empacotar.sh` não estava na estrutura pedida**: entrou para garantir o `Dockerfile` na
  raiz do zip e o mesmo pacote no console e no SAM.
