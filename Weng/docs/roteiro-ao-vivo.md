# Roteiro ao vivo: Corrida na Nuvem

Região em todas as telas: **us-east-1 (N. Virgínia)**. Confira no canto superior do console antes de
cada serviço.

Duração no palco: cerca de 20 minutos.

**Nunca mostre no projetor:** a aba de variáveis de ambiente da Lambda e o campo do token em texto
puro.

---

## Preparação (dias antes)

Tudo aqui é feito **fora do palco**. Os comandos e recursos criados podem gerar custo.

**Se você subiu tudo com Terraform (veja o README), pule para o passo 9.** Os nomes são os mesmos
deste roteiro; só o domínio do telão ganha um sufixo, mostrado em `url_telao`. O deploy ao vivo do
passo 3 pelo console funciona normalmente, mas o próximo `terraform apply` volta para a versão do
repositório.

### 1. Gerar os zips e o token

```bash
./scripts/empacotar.sh
```

```bash
openssl rand -hex 24
```

Guarde o token no seu gerenciador de senhas. Ele não vai para o repositório.

### 2. Criar a tabela

DynamoDB → **Create table**

- Nome: `corrida-na-nuvem`
- Partition key: `pk`, tipo String
- Table settings: **Customize settings** → Capacity mode: **On-demand**

### 3. Criar o papel da Lambda

IAM → Roles → **Create role** → AWS service → Lambda → sem políticas → nome
`corrida-na-nuvem-lambda`. Depois, **Add permissions → Create inline policy → JSON**, trocando
`<CONTA>`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PlacarNoDynamoDB",
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:UpdateItem"],
      "Resource": "arn:aws:dynamodb:us-east-1:<CONTA>:table/corrida-na-nuvem"
    },
    {
      "Sid": "LocutorNoBedrock",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0"
    },
    {
      "Sid": "LogsNoCloudWatch",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:<CONTA>:log-group:/aws/lambda/corrida-na-nuvem:*"
    }
  ]
}
```

A API Converse usa a permissão `bedrock:InvokeModel`; não existe uma permissão separada para ela.

### 4. Criar a Lambda

Lambda → **Create function** → Author from scratch

- Nome: `corrida-na-nuvem`
- Runtime: **Python 3.13**
- Arquitetura: **x86_64** (é o preço usado na estimativa)
- Execution role: use existing → `corrida-na-nuvem-lambda`

Depois:

- Code → **Upload from → .zip file** → `dist/api.zip`
- Runtime settings: handler `lambda_function.lambda_handler` (já é o padrão)
- Configuration → General: **timeout 10 s, memória 256 MB**
- Configuration → Environment variables: `TABLE_NAME=corrida-na-nuvem` e `ADMIN_TOKEN=<seu token>`

### 5. Criar a API

API Gateway → **Create API** → HTTP API → Build

- Integration: Lambda → `corrida-na-nuvem`
- Nome: `corrida-api`
- Rotas, todas para a mesma Lambda:
  - `GET /`
  - `POST /tap`
  - `GET /state`
  - `POST /admin/start`
  - `POST /admin/reset`
- Stage: **`$default`** com auto-deploy. O código espera este stage: um stage com nome colocaria um
  prefixo nas URLs e quebraria as rotas.

Anote a **Invoke URL**: é o `API_URL`.

### 6. Criar o perfil de instância do Beanstalk

A AWS não cria mais `aws-elasticbeanstalk-ec2-role` automaticamente, e ele **precisa existir antes**
do ambiente. A service role, sim, o console cria.

IAM → Roles → **Create role** → AWS service → EC2 → política `AWSElasticBeanstalkWebTier` → nome
`aws-elasticbeanstalk-ec2-role`. Esta demo não usa worker nem Docker gerenciado por ECS, então as
outras duas políticas que a documentação lista para o caso geral não são necessárias.

### 7. Subir o telão

Elastic Beanstalk → **Create application**: `corrida-na-nuvem`. Depois, **Create environment**:

- Web server environment; nome `corrida-telao`; domínio `corrida-telao` se estiver livre
- Platform: **Docker**, branch Amazon Linux 2023
- Application code: **Upload your code** → `dist/telao.zip`, versão `v1`
- Presets: **Single instance** (sem load balancer, mais barato)
- Service role: **Create and use new service role**
- EC2 instance profile: `aws-elasticbeanstalk-ec2-role`
- Tipo de instância: `t3.micro`
- **Deactivate IMDSv1: deixe marcado.** Contas criadas depois de 1º/10/2024 não podem usar launch
  configurations, e esta opção faz o Beanstalk usar launch template. Se a criação falhar citando
  launch configuration, confira esta opção ou defina o root volume como `gp3`.
- Software → Environment properties: `API_URL` = Invoke URL da API

A criação leva alguns minutos. Faça com folga, nunca no palco.

### 8. Liberar o CORS

API Gateway → `corrida-api` → **CORS** → Configure

- Access-Control-Allow-Origin: `http://corrida-telao.us-east-1.elasticbeanstalk.com`
  (a URL real do ambiente, **com `http://` e sem barra no final**)
- Access-Control-Allow-Methods: `GET`, `POST`
- Access-Control-Allow-Headers: `x-admin-token`

### 9. Preparar a versão do deploy ao vivo

Para o deploy do passo 3 ter um efeito visível, faça uma segunda versão com outro título:

1. Em `telao/public/index.html`, troque o `<h1>` para `Corrida na Nuvem ao vivo`.
2. Rode `./scripts/empacotar.sh`.
3. Copie `dist/telao.zip` para `~/Desktop/telao-v2.zip`.
4. Desfaça a troca do título.

---

## Checklist da véspera

Com antecedência de **dias**:

- [ ] **Quota de concorrência da Lambda.** Veja o limite atual:
  ```bash
  aws lambda get-account-settings --region us-east-1 --query AccountLimit.ConcurrentExecutions
  ```
  O padrão é 1.000, mas contas novas podem vir com bem menos. Em regime são poucas execuções
  simultâneas, porém a largada gera um pico de partidas a frio. Se estiver baixo, peça aumento em
  **Service Quotas → AWS Lambda → Concurrent executions**. A aprovação pode levar dias.
- [ ] **Alerta do AWS Budgets** criado (veja o README).

Na véspera:

- [ ] **Modelo no Bedrock.** A antiga página "Model access" foi aposentada, e os modelos ficam
  habilitados por padrão, então o teste é chamar o modelo. Confira que ele continua ativo:
  ```bash
  aws bedrock get-foundation-model --model-identifier amazon.nova-micro-v1:0 --region us-east-1 --query modelDetails.modelLifecycle.status
  ```
  E faça uma chamada real (custa frações de centavo):
  ```bash
  aws bedrock-runtime converse --model-id amazon.nova-micro-v1:0 --region us-east-1 --messages '[{"role":"user","content":[{"text":"Diga oi em português."}]}]' --inference-config '{"maxTokens":60}'
  ```
- [ ] **Quota do modelo.** Contas novas podem vir com quota **zero** no Bedrock: a chamada acima
  responde `Too many tokens per day` e o locutor fica mudo, sem erro na tela. Confira:
  ```bash
  aws service-quotas list-service-quotas --service-code bedrock --region us-east-1 --query "Quotas[?contains(QuotaName,'Nova Micro') && contains(QuotaName,'per day')].[QuotaName,Value]" --output text
  ```
  Se vier 0, esta quota não pode ser alterada pelo Service Quotas: abra um chamado no AWS Support
  com dias de antecedência.
- [ ] **Teste de carga leve**, com o telão aberto e sem clicar em Largada ou Zerar durante o teste. Custa cerca de 1 centavo de dólar por rodada:
  ```bash
  python3 scripts/carga.py --url https://SEU-ID.execute-api.us-east-1.amazonaws.com --jogadores 100
  ```
  Dê a largada no telão. Esperado: zero em `429/5xx` e "Tudo certo". Se aparecer 429/5xx, volte à
  quota de concorrência.
- [ ] **Duração real.** Depois do teste, troque `DURACAO_MEDIA_LAMBDA_S` no topo de
  `telao/public/index.html` pela média do CloudWatch e refaça o zip e o deploy.
- [ ] **Celulares reais**: um iPhone e um Android, no 4G e no Wi-Fi. O iPhone não vibra (o Safari não
  tem `navigator.vibrate`); o retorno nele é só visual.
- [ ] **QR** lido do fundo de uma sala parecida. A URL em texto também aparece no telão.
- [ ] **Locutor**: durante o teste, as frases mudam a cada ~10 s. Se o nome na caixa for "Locutor de
  reserva", o Bedrock falhou e a frase é pronta. O motivo aparece nos logs da Lambda: `Locutor usou
  frase de reserva`. Enquanto estiver assim, não apresente a frase como gerada pelo modelo.

Antes da palestra (30 min):

- [ ] Abra as abas nesta ordem: DynamoDB, Lambda, API Gateway, Beanstalk, telão, CloudWatch.
- [ ] Digite o token no telão **antes de ligar o projetor**. Clique em Zerar para confirmar que ele
  está certo.
- [ ] Para a tabela aparecer vazia: DynamoDB → Explore items → selecione `game#current` → **Delete
  item**. A primeira Largada recria o item.
- [ ] Celular carregado, com 4G funcionando, e hotspot pronto para o plano B.
- [ ] Vídeo de uma rodada do ensaio guardado como último recurso.

---

## No palco

### Passo 1. A tabela vazia (1 min)

DynamoDB → `corrida-na-nuvem` → **Explore table items** → 0 itens.

> "Este é o banco inteiro do jogo. Sem servidor, sem tamanho para escolher. Pago por escrita. Daqui
> a pouco, todo o placar vai morar em um único item."

### Passo 2. A Lambda e as rotas (4 min)

1. Lambda → `corrida-na-nuvem` → **Code**: mostre `lambda_handler` e o dicionário `ROTAS`. (1 min)
2. Mostre `rota_tap` e o comentário do `ADD`. (1 min)
3. Configuration → **Permissions**: abra o papel e mostre a política, sem `"Action": "*"`. (1 min)
4. API Gateway → `corrida-api` → **Routes**: as 5 rotas. Copie a Invoke URL e abra no seu celular. (1 min)

> Não abra **Configuration → Environment variables**: o token aparece ali.

Prefira mostrar pronto. Se quiser criar algo ao vivo, crie só uma rota de teste: a criação completa
leva mais tempo do que o bloco tem.

### Passo 3. O telão no Beanstalk (3 min)

1. Elastic Beanstalk → `corrida-telao`: mostre a saúde **Ok**, a plataforma Docker e a variável
   `API_URL`. (1 min)
2. **Upload and deploy** → `telao-v2.zip`, versão `v2-ao-vivo`. (30 s)
3. Enquanto o deploy roda (1 a 3 min), explique que o `Dockerfile` está na raiz do zip e que o
   primeiro `EXPOSE` define a porta usada.
4. Recarregue o telão: o título mudou.

> Com instância única, o telão fica fora do ar por instantes durante o deploy. **Nunca faça deploy
> com rodada em andamento.** A API não é afetada, então os celulares continuam funcionando.

### Passo 4. As rodadas (6 a 8 min)

1. Telão em tela cheia. "Apontem a câmera para o QR e escolham uma Região." Dê 1 minuto. Se o Wi-Fi
   estiver ruim, peça para usarem o 4G.
2. **Largada**. 60 segundos. Comente a corrida junto com o locutor. Os celulares descobrem a largada
   em até 2 s.
3. Resultado: vencedor, requisições e custo. Comente o número de requisições.
4. Repita 1 ou 2 vezes. A Largada já zera o placar; use **Zerar** só para limpar a tela.

Na primeira rodada, aproveite para mostrar a tabela de novo: agora ela tem um item, e os contadores
batem com o telão.

### Passo 5. CloudWatch (3 min)

Lambda → `corrida-na-nuvem` → **Monitor**. As métricas chegam com **1 a 2 minutos de atraso**: fale
do custo primeiro se o gráfico ainda não tiver atualizado.

- **Invocations**: o pico por minuto. Com 100 pessoas, cerca de 6.000 em uma rodada.
- **Duration**: média baixa, em milissegundos. Os picos isolados são partidas a frio e chamadas ao
  Bedrock.
- **ConcurrentExecutions**: quantos ambientes rodaram ao mesmo tempo.
- **Errors** e **Throttles**: o número que você quer mostrar é zero.

A menor resolução padrão é de 1 minuto, então o pico aparece por minuto, não por segundo. O total
aqui é um pouco maior que o do telão, porque inclui o carregamento da página e as consultas fora da
rodada.

### Passo 6. O custo (1 min)

Volte ao telão. A conta usa os preços de `us-east-1` e não inclui o nível gratuito.

> "Essa rodada custou cerca de um centavo de dólar. Fica de fora o Beanstalk, cobrado por hora e não
> por toque. E é por isso que apagar tudo depois da palestra faz parte da demo."

**Depois da palestra: siga "Apagar tudo" no README, no mesmo dia.**

---

## Plano B

### Wi-Fi ruim

1. Peça para a sala desligar o Wi-Fi e usar o 4G. A API é pública e não depende da rede do local.
2. Se o seu notebook estiver sem rede, use o hotspot do celular nele.
3. **Rodada só com o seu celular:** abra a URL do jogador no 4G, dê a largada e toque você mesma. A
   demo é a mesma, só que com um competidor. Dá para contar a história: "agora imaginem 100 de mim".
4. Se o notebook tiver internet, mas a sala não, rode a carga para animar as barras e dê a largada
   no telão:
   ```bash
   python3 scripts/carga.py --url https://SEU-ID.execute-api.us-east-1.amazonaws.com --jogadores 30
   ```
5. Último recurso: o vídeo do ensaio.

### Console travado ou lento

Deploy da API por SAM, em um comando (veja o README). Depois, atualize `API_URL` no Beanstalk.

### Beanstalk fora do ar

Rode o telão no seu notebook:

```bash
docker build -t corrida-telao telao
```

```bash
docker run --rm -p 8080:8080 -e API_URL=https://SEU-ID.execute-api.us-east-1.amazonaws.com corrida-telao
```

Abra `http://localhost:8080` e adicione `http://localhost:8080` em **API Gateway → CORS →
Access-Control-Allow-Origin**.

### O telão diz "Sem resposta da API"

Quase sempre é CORS. Confira se a origem configurada é idêntica à barra de endereço do telão, com
`http://` e sem barra no final. Depois, teste `https://SEU-ID.execute-api.us-east-1.amazonaws.com/state`
direto no navegador: se responder, o problema é só o CORS.

### Apareceu "Locutor de reserva"

A corrida segue normal: em caso de erro ou throttling no Bedrock, a Lambda usa uma frase pronta com o
placar real e tenta o modelo de novo em 10 s. Vire a história: "o modelo falhou, e a demo continuou.
É para isso que serve um plano de reserva". Investigue depois, pelos logs da Lambda.

### Celulares recebendo erro na largada

Provavelmente é throttling na Lambda, por causa da quota baixa. Os toques ficam guardados nos
celulares e são reenviados a cada segundo: a corrida se recupera sozinha, sem perder toques. Depois,
mostre **Throttles** no CloudWatch. Vira um bom exemplo de por que pedir a quota antes.
