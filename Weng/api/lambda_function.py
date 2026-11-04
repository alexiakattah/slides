"""Corrida na Nuvem: uma única Lambda atrás do API Gateway (HTTP API).

Rotas:
    GET  /             página do jogador (celular)
    POST /tap          soma toques de um time
    GET  /state        placar para o telão e, no máximo a cada 10 s, a frase do locutor
    POST /admin/start  inicia uma rodada de 60 s (exige x-admin-token)
    POST /admin/reset  zera o placar (exige x-admin-token)

Todo o estado do jogo mora em um único item do DynamoDB.
"""

import base64
import hmac
import json
import os
import time
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# ---------------------------------------------------------------- configuração

REGIAO = "us-east-1"
MODELO = "amazon.nova-micro-v1:0"

TIMES = {"sp": "São Paulo", "va": "Virgínia", "tk": "Tóquio", "fr": "Frankfurt"}
MAX_TOQUES_POR_REQUISICAO = 50
DURACAO_RODADA_S = 60
INTERVALO_LOCUTOR_S = 10

CHAVE_DO_JOGO = {"pk": "game#current"}

PROMPT_LOCUTOR = (
    "Você é um locutor esportivo animado narrando uma corrida de toques entre "
    "times de estudantes. Responda em português do Brasil, em uma única frase "
    "de até 20 palavras, sem emojis."
)

# Usadas só quando o Bedrock falha. O placar é real; o texto é pronto, não vem do modelo.
FRASES_DE_RESERVA = [
    "{lider} lidera com {pontos} toques, mas {segundo} ainda pode virar essa corrida!",
    "Que ritmo! {lider} abre {diferenca} toques de vantagem sobre {segundo}!",
    "{segundo} persegue {lider}, e a diferença está em {diferenca} toques!",
    "Olha a disputa: {lider} na frente, {segundo} logo atrás! Não parem de tocar!",
    "{lider} segue na ponta com {pontos} toques! Quem vai tirar essa liderança?",
]
FRASE_DE_EMPATE = "Empate na ponta entre {lider} e {segundo}! Cada toque agora vale ouro!"
FRASE_SEM_TOQUES = "Largada dada e o placar segue zerado! Quem vai tocar primeiro?"

# Os clientes ficam fora do handler: a Lambda reaproveita o mesmo ambiente entre
# invocações, então a conexão só é aberta na primeira chamada (a "partida a frio").
# Os timeouts curtos garantem uma falha rápida, dentro dos 10 s da Lambda.
tabela = boto3.resource(
    "dynamodb",
    region_name=REGIAO,
    config=Config(connect_timeout=1, read_timeout=2, retries={"max_attempts": 2}),
).Table(os.environ.get("TABLE_NAME", "corrida-na-nuvem"))

bedrock = boto3.client(
    "bedrock-runtime",
    region_name=REGIAO,
    config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
)

# A página do jogador vai junto no zip e é lida uma vez, na partida a frio.
PAGINA_JOGADOR = (Path(__file__).parent / "player.html").read_text(encoding="utf-8")


def agora():
    """Hora atual em segundos. Fica em uma função para os testes controlarem o tempo."""
    return int(time.time())


# ----------------------------------------------------------------- respostas


def _json_padrao(valor):
    """O DynamoDB devolve números como Decimal; o JSON precisa de int."""
    if isinstance(valor, Decimal):
        return int(valor)
    raise TypeError(f"Tipo não serializável: {type(valor)}")


def resposta_json(status_http, corpo):
    return {
        "statusCode": status_http,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(corpo, default=_json_padrao, ensure_ascii=False),
    }


def condicao_falhou(erro):
    """True quando o DynamoDB recusou a escrita porque a condição era falsa."""
    return erro.response["Error"]["Code"] == "ConditionalCheckFailedException"


# ---------------------------------------------------------------------- jogo


def rodada_ativa(item, instante):
    """O status fica "running" até o próximo start/reset; quem encerra é o relógio."""
    return item.get("status") == "running" and int(item.get("endsAt", 0)) > instante


def status_visivel(item, instante):
    if rodada_ativa(item, instante):
        return "running"
    return "finished" if item.get("status") == "running" else "waiting"


def ler_jogo():
    # ConsistentRead: o telão precisa enxergar a última escrita, não uma cópia atrasada.
    return tabela.get_item(Key=CHAVE_DO_JOGO, ConsistentRead=True).get("Item", {})


def escrita_placar_zerado(status, ends_at, narrated_at):
    """Parâmetros do UpdateItem que zera o placar. É o que start e reset têm em comum."""
    return {
        "Key": CHAVE_DO_JOGO,
        "UpdateExpression": (
            "SET #status = :status, endsAt = :endsAt, narratedAt = :narratedAt, "
            "phrase = :vazio, phraseSource = :vazio, "
            "sp = :zero, va = :zero, tk = :zero, fr = :zero, requests = :zero"
        ),
        # "status" é palavra reservada no DynamoDB, por isso o apelido #status.
        "ExpressionAttributeNames": {"#status": "status"},
        "ExpressionAttributeValues": {
            ":status": status,
            ":endsAt": ends_at,
            ":narratedAt": narrated_at,
            ":vazio": "",
            ":zero": 0,
        },
    }


# -------------------------------------------------------------------- locutor


def gerar_frase(item):
    """Pede ao Nova Micro uma frase sobre o placar atual."""
    placar = ", ".join(f"{nome}: {int(item.get(t, 0))}" for t, nome in TIMES.items())
    resposta = bedrock.converse(
        modelId=MODELO,
        system=[{"text": PROMPT_LOCUTOR}],
        messages=[{"role": "user", "content": [{"text": f"Placar atual: {placar}."}]}],
        inferenceConfig={"maxTokens": 60},
    )
    return resposta["output"]["message"]["content"][0]["text"].strip()


def frase_de_reserva(item, instante):
    """Monta uma frase pronta com o placar real, sem chamar nenhum modelo."""
    ordem = sorted(TIMES, key=lambda t: int(item.get(t, 0)), reverse=True)
    primeiro, segundo = int(item.get(ordem[0], 0)), int(item.get(ordem[1], 0))
    dados = {
        "lider": TIMES[ordem[0]],
        "segundo": TIMES[ordem[1]],
        "pontos": primeiro,
        "diferenca": primeiro - segundo,
    }
    if primeiro == 0:
        return FRASE_SEM_TOQUES
    if primeiro == segundo:
        return FRASE_DE_EMPATE.format(**dados)
    # O relógio escolhe a frase: assim o locutor não repete a anterior.
    posicao = instante // INTERVALO_LOCUTOR_S % len(FRASES_DE_RESERVA)
    return FRASES_DE_RESERVA[posicao].format(**dados)


def atualizar_locutor(item, instante):
    """Devolve (frase, origem), gerando uma frase nova só quando já passou da hora."""
    frase_atual = item.get("phrase", ""), item.get("phraseSource", "")
    limite = instante - INTERVALO_LOCUTOR_S

    if not rodada_ativa(item, instante) or int(item.get("narratedAt", 0)) >= limite:
        return frase_atual

    # Escrita condicional: várias chamadas podem chegar aqui ao mesmo tempo, mas o
    # DynamoDB só aceita a primeira. É ela, e só ela, que paga a chamada ao Bedrock.
    try:
        tabela.update_item(
            Key=CHAVE_DO_JOGO,
            UpdateExpression="SET narratedAt = :agora",
            ConditionExpression="narratedAt < :limite",
            ExpressionAttributeValues={":agora": instante, ":limite": limite},
        )
    except ClientError as erro:
        if condicao_falhou(erro):
            return frase_atual
        raise

    # Throttling ou qualquer outro erro: entra a frase de reserva e a corrida continua.
    # narratedAt já avançou, então o Bedrock só é tentado de novo daqui a 10 s.
    try:
        frase_nova, origem = gerar_frase(item), "bedrock"
    except (ClientError, BotoCoreError, KeyError, IndexError) as erro:
        print(f"Locutor usou frase de reserva: {erro}")
        frase_nova, origem = frase_de_reserva(item, instante), "reserva"

    tabela.update_item(
        Key=CHAVE_DO_JOGO,
        UpdateExpression="SET phrase = :frase, phraseSource = :origem",
        ExpressionAttributeValues={":frase": frase_nova, ":origem": origem},
    )
    return frase_nova, origem


# ---------------------------------------------------------------------- rotas


def rota_pagina_jogador(_evento):
    return {
        "statusCode": 200,
        "headers": {"content-type": "text/html; charset=utf-8"},
        "body": PAGINA_JOGADOR,
    }


def ler_corpo_json(evento):
    corpo = evento.get("body") or ""
    if evento.get("isBase64Encoded"):
        corpo = base64.b64decode(corpo).decode("utf-8")
    return json.loads(corpo)


def rota_tap(evento):
    try:
        dados = ler_corpo_json(evento)
    except (ValueError, UnicodeDecodeError):
        return resposta_json(400, {"error": "corpo inválido"})
    if not isinstance(dados, dict):
        return resposta_json(400, {"error": "corpo inválido"})

    time_id = dados.get("team")
    count = dados.get("count")

    if not isinstance(time_id, str) or time_id not in TIMES:
        return resposta_json(400, {"error": "time inválido"})
    # bool é subclasse de int em Python: sem esse teste, true valeria 1 toque.
    if isinstance(count, bool) or not isinstance(count, int):
        return resposta_json(400, {"error": "count inválido"})
    if not 1 <= count <= MAX_TOQUES_POR_REQUISICAO:
        return resposta_json(400, {"error": "count fora do limite"})

    instante = agora()
    try:
        # ADD é atômico: 100 celulares somando ao mesmo tempo não perdem nenhum toque.
        # Ler, somar e gravar de volta perderia, porque um sobrescreveria o outro.
        atualizado = tabela.update_item(
            Key=CHAVE_DO_JOGO,
            UpdateExpression="ADD #time :count, requests :um",
            ConditionExpression="#status = :running AND endsAt > :agora",
            ExpressionAttributeNames={"#time": time_id, "#status": "status"},
            ExpressionAttributeValues={
                ":count": count,
                ":um": 1,
                ":running": "running",
                ":agora": instante,
            },
            ReturnValues="ALL_NEW",
        )["Attributes"]
    except ClientError as erro:
        if condicao_falhou(erro):
            return resposta_json(409, {"ok": False, "error": "rodada não está ativa"})
        raise

    return resposta_json(
        200,
        {"ok": True, "secondsLeft": max(0, int(atualizado["endsAt"]) - instante)},
    )


def rota_state(_evento):
    instante = agora()
    item = ler_jogo()
    ativa = rodada_ativa(item, instante)
    requisicoes = int(item.get("requests", 0))

    # Só conta durante a rodada, para o total e o custo não subirem depois do fim.
    if ativa:
        tabela.update_item(
            Key=CHAVE_DO_JOGO,
            UpdateExpression="ADD requests :um",
            ExpressionAttributeValues={":um": 1},
        )
        requisicoes += 1

    frase, origem_da_frase = atualizar_locutor(item, instante)
    placar = {t: int(item.get(t, 0)) for t in TIMES}

    return resposta_json(
        200,
        {
            "status": status_visivel(item, instante),
            "secondsLeft": max(0, int(item.get("endsAt", 0)) - instante) if ativa else 0,
            "scores": placar,
            "totalTaps": sum(placar.values()),
            "requests": requisicoes,
            "phrase": frase,
            "phraseSource": origem_da_frase,
        },
    )


def token_valido(evento):
    # Sem ADMIN_TOKEN configurado, ninguém entra. Nunca existe um token padrão.
    esperado = os.environ.get("ADMIN_TOKEN", "")
    # O HTTP API entrega os nomes dos headers em minúsculas.
    recebido = (evento.get("headers") or {}).get("x-admin-token", "")
    # compare_digest leva o mesmo tempo com token certo ou errado.
    return bool(esperado) and hmac.compare_digest(
        esperado.encode("utf-8"), recebido.encode("utf-8")
    )


def rota_admin_start(_evento):
    instante = agora()
    # narratedAt = agora: a primeira frase do locutor sai 10 s depois da largada.
    escrita = escrita_placar_zerado("running", instante + DURACAO_RODADA_S, instante)
    escrita["ExpressionAttributeValues"][":agora"] = instante
    try:
        tabela.update_item(
            # Um clique duplo em Largada não pode zerar uma rodada em andamento.
            ConditionExpression=(
                "attribute_not_exists(#status) OR #status <> :status OR endsAt <= :agora"
            ),
            **escrita,
        )
    except ClientError as erro:
        if condicao_falhou(erro):
            return resposta_json(409, {"ok": False, "error": "rodada em andamento"})
        raise
    return resposta_json(200, {"ok": True, "secondsLeft": DURACAO_RODADA_S})


def rota_admin_reset(_evento):
    tabela.update_item(**escrita_placar_zerado("waiting", 0, 0))
    return resposta_json(200, {"ok": True})


ROTAS = {
    ("GET", "/"): rota_pagina_jogador,
    ("POST", "/tap"): rota_tap,
    ("GET", "/state"): rota_state,
    ("POST", "/admin/start"): rota_admin_start,
    ("POST", "/admin/reset"): rota_admin_reset,
}


def lambda_handler(evento, _contexto):
    http = evento["requestContext"]["http"]
    metodo, caminho = http["method"], evento["rawPath"]

    rota = ROTAS.get((metodo, caminho))
    if rota is None:
        return resposta_json(404, {"error": "rota não encontrada"})
    if caminho.startswith("/admin/") and not token_valido(evento):
        return resposta_json(401, {"error": "token inválido"})

    try:
        return rota(evento)
    except (ClientError, BotoCoreError) as erro:
        # O celular guarda os toques não enviados e tenta de novo no segundo seguinte.
        print(f"Erro na AWS em {metodo} {caminho}: {erro}")
        return resposta_json(503, {"error": "tente novamente"})
