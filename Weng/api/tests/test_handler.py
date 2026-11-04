"""Testes da Lambda: DynamoDB simulado pelo moto e Bedrock simulado por um stub.

Nada aqui fala com a AWS nem gasta dinheiro.
"""

import importlib
import json
import sys
from pathlib import Path

import boto3
import pytest
from botocore.stub import Stubber
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TOKEN_DE_TESTE = "token-apenas-para-teste"
INICIO = 1_000_000


@pytest.fixture
def lf(monkeypatch):
    """Módulo da Lambda com tabela simulada, relógio fixo e Bedrock sem respostas."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "teste")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "teste")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "corrida-teste")
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN_DE_TESTE)

    with mock_aws():
        boto3.client("dynamodb", region_name="us-east-1").create_table(
            TableName="corrida-teste",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        modulo = importlib.import_module("lambda_function")
        modulo = importlib.reload(modulo)
        monkeypatch.setattr(modulo, "agora", lambda: INICIO)
        yield modulo


@pytest.fixture
def bedrock(lf):
    """Stubber valida a chamada contra o esquema real da API do Bedrock."""
    with Stubber(lf.bedrock) as stub:
        yield stub
        stub.assert_no_pending_responses()


def evento(metodo, caminho, corpo=None, token=None, base64=False):
    headers = {"x-admin-token": token} if token else {}
    if isinstance(corpo, (dict, list)):
        corpo = json.dumps(corpo)
    return {
        "rawPath": caminho,
        "headers": headers,
        "body": corpo,
        "isBase64Encoded": base64,
        "requestContext": {"http": {"method": metodo}},
    }


def chamar(lf, *args, **kwargs):
    resposta = lf.lambda_handler(evento(*args, **kwargs), None)
    corpo = resposta["body"]
    if resposta["headers"]["content-type"].startswith("application/json"):
        corpo = json.loads(corpo)
    return resposta["statusCode"], corpo


def largar(lf):
    status, _ = chamar(lf, "POST", "/admin/start", token=TOKEN_DE_TESTE)
    assert status == 200


def mover_relogio(lf, monkeypatch, segundos):
    monkeypatch.setattr(lf, "agora", lambda: INICIO + segundos)


def resposta_bedrock(texto):
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": texto}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
        "metrics": {"latencyMs": 100},
    }


# ------------------------------------------------------------------ rotas gerais


def test_pagina_do_jogador_e_html(lf):
    resposta = lf.lambda_handler(evento("GET", "/"), None)
    assert resposta["statusCode"] == 200
    assert resposta["headers"]["content-type"].startswith("text/html")
    assert "Corrida na Nuvem" in resposta["body"]


def test_rota_desconhecida_da_404(lf):
    assert chamar(lf, "GET", "/nao-existe")[0] == 404
    assert chamar(lf, "GET", "/tap")[0] == 404


def test_erro_da_aws_vira_503_para_o_celular_tentar_de_novo(lf, monkeypatch):
    from botocore.exceptions import EndpointConnectionError

    def falhar(**_):
        raise EndpointConnectionError(endpoint_url="https://dynamodb")

    monkeypatch.setattr(lf.tabela, "get_item", falhar)
    assert chamar(lf, "GET", "/state")[0] == 503


# ------------------------------------------------------------------------- /tap


def test_tap_soma_no_time_certo_e_conta_a_requisicao(lf):
    largar(lf)
    status, corpo = chamar(lf, "POST", "/tap", {"team": "sp", "count": 7})
    assert status == 200
    assert corpo == {"ok": True, "secondsLeft": 60}
    chamar(lf, "POST", "/tap", {"team": "sp", "count": 3})
    chamar(lf, "POST", "/tap", {"team": "fr", "count": 50})

    _, estado = chamar(lf, "GET", "/state")
    assert estado["scores"] == {"sp": 10, "va": 0, "tk": 0, "fr": 50}
    assert estado["totalTaps"] == 60
    assert estado["requests"] == 4  # 3 toques + este /state


def test_tap_aceita_corpo_em_base64(lf):
    import base64

    largar(lf)
    corpo = base64.b64encode(b'{"team":"tk","count":2}').decode()
    assert chamar(lf, "POST", "/tap", corpo, base64=True)[0] == 200


def test_tap_e_uma_unica_escrita_atomica_sem_leitura(lf, monkeypatch):
    largar(lf)
    chamadas = []
    atualizar = lf.tabela.update_item

    def espiar_update(**kwargs):
        chamadas.append(kwargs)
        return atualizar(**kwargs)

    def proibir_leitura(**_):
        pytest.fail("/tap não pode ler antes de escrever")

    monkeypatch.setattr(lf.tabela, "update_item", espiar_update)
    monkeypatch.setattr(lf.tabela, "get_item", proibir_leitura)

    assert chamar(lf, "POST", "/tap", {"team": "va", "count": 1})[0] == 200
    assert len(chamadas) == 1
    assert chamadas[0]["UpdateExpression"].startswith("ADD ")


def test_tap_antes_da_largada_nao_conta(lf):
    assert chamar(lf, "POST", "/tap", {"team": "sp", "count": 5})[0] == 409
    chamar(lf, "POST", "/admin/reset", token=TOKEN_DE_TESTE)
    assert chamar(lf, "POST", "/tap", {"team": "sp", "count": 5})[0] == 409
    assert chamar(lf, "GET", "/state")[1]["totalTaps"] == 0


def test_tap_depois_do_fim_nao_conta(lf, monkeypatch):
    largar(lf)
    chamar(lf, "POST", "/tap", {"team": "sp", "count": 5})
    mover_relogio(lf, monkeypatch, 60)
    assert chamar(lf, "POST", "/tap", {"team": "sp", "count": 5})[0] == 409
    assert chamar(lf, "GET", "/state")[1]["scores"]["sp"] == 5


@pytest.mark.parametrize(
    "corpo",
    [
        {"team": "xx", "count": 1},
        {"team": "SP", "count": 1},
        {"team": "requests", "count": 1},  # não pode virar atalho para outro atributo
        {"team": "status", "count": 1},
        {"team": ["sp"], "count": 1},
        {"team": None, "count": 1},
        {"count": 1},
        {"team": "sp", "count": 0},
        {"team": "sp", "count": -1},
        {"team": "sp", "count": 51},
        {"team": "sp", "count": "5"},
        {"team": "sp", "count": 1.5},
        {"team": "sp", "count": True},
        {"team": "sp"},
        ["sp", 1],
        "isto não é json",
        "",
        None,
    ],
)
def test_tap_invalido_da_400_e_nao_conta(lf, corpo):
    largar(lf)
    assert chamar(lf, "POST", "/tap", corpo)[0] == 400
    assert chamar(lf, "GET", "/state")[1]["totalTaps"] == 0


def test_tap_nunca_chama_o_bedrock(lf, monkeypatch, bedrock):
    # O stub sem respostas falharia em qualquer chamada, mesmo com a frase vencida.
    largar(lf)
    mover_relogio(lf, monkeypatch, 30)
    assert chamar(lf, "POST", "/tap", {"team": "sp", "count": 1})[0] == 200


# ----------------------------------------------------------------------- /state


def test_state_antes_do_primeiro_start(lf):
    status, corpo = chamar(lf, "GET", "/state")
    assert status == 200
    assert corpo == {
        "status": "waiting",
        "secondsLeft": 0,
        "scores": {"sp": 0, "va": 0, "tk": 0, "fr": 0},
        "totalTaps": 0,
        "requests": 0,
        "phrase": "",
        "phraseSource": "",
    }


def test_state_mostra_tempo_restante_e_fim_da_rodada(lf, monkeypatch):
    largar(lf)
    mover_relogio(lf, monkeypatch, 5)
    _, corpo = chamar(lf, "GET", "/state")
    assert (corpo["status"], corpo["secondsLeft"]) == ("running", 55)

    mover_relogio(lf, monkeypatch, 60)
    _, corpo = chamar(lf, "GET", "/state")
    assert (corpo["status"], corpo["secondsLeft"]) == ("finished", 0)


def test_total_de_requisicoes_para_de_subir_depois_do_fim(lf, monkeypatch):
    largar(lf)
    chamar(lf, "POST", "/tap", {"team": "sp", "count": 1})
    mover_relogio(lf, monkeypatch, 61)
    primeira = chamar(lf, "GET", "/state")[1]["requests"]
    segunda = chamar(lf, "GET", "/state")[1]["requests"]
    assert primeira == segunda == 1


# ---------------------------------------------------------------------- locutor


def test_locutor_nao_fala_antes_de_10_segundos(lf, monkeypatch, bedrock):
    largar(lf)
    mover_relogio(lf, monkeypatch, 10)  # exatamente 10 s: ainda não passou de 10 s
    assert chamar(lf, "GET", "/state")[1]["phrase"] == ""


def test_locutor_fala_depois_de_10_segundos_com_o_prompt_certo(lf, monkeypatch, bedrock):
    largar(lf)
    chamar(lf, "POST", "/tap", {"team": "sp", "count": 12})
    bedrock.add_response(
        "converse",
        resposta_bedrock(" São Paulo dispara na frente! "),
        {
            "modelId": "amazon.nova-micro-v1:0",
            "system": [
                {
                    "text": "Você é um locutor esportivo animado narrando uma corrida "
                    "de toques entre times de estudantes. Responda em português do "
                    "Brasil, em uma única frase de até 20 palavras, sem emojis."
                }
            ],
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "text": "Placar atual: São Paulo: 12, Virgínia: 0, "
                            "Tóquio: 0, Frankfurt: 0."
                        }
                    ],
                }
            ],
            "inferenceConfig": {"maxTokens": 60},
        },
    )
    mover_relogio(lf, monkeypatch, 11)
    corpo = chamar(lf, "GET", "/state")[1]
    assert (corpo["phrase"], corpo["phraseSource"]) == ("São Paulo dispara na frente!", "bedrock")

    # A chamada seguinte reaproveita a frase salva, sem outro Bedrock.
    mover_relogio(lf, monkeypatch, 15)
    corpo = chamar(lf, "GET", "/state")[1]
    assert (corpo["phrase"], corpo["phraseSource"]) == ("São Paulo dispara na frente!", "bedrock")


def test_apenas_uma_chamada_concorrente_gera_a_frase(lf, monkeypatch, bedrock):
    """Duas chamadas leem o item vencido ao mesmo tempo; só a primeira chama o Bedrock."""
    largar(lf)
    mover_relogio(lf, monkeypatch, 11)
    item_vencido = lf.ler_jogo()

    bedrock.add_response("converse", resposta_bedrock("Frase única"))
    assert lf.atualizar_locutor(item_vencido, INICIO + 11) == ("Frase única", "bedrock")

    # A segunda usa a mesma leitura antiga; a condição falha e não há outra resposta
    # no stub, então uma chamada indevida ao Bedrock derrubaria este teste.
    assert lf.atualizar_locutor(item_vencido, INICIO + 11) == ("", "")


def test_throttling_usa_frase_de_reserva_com_o_placar_real(lf, monkeypatch, bedrock):
    largar(lf)
    chamar(lf, "POST", "/tap", {"team": "tk", "count": 30})
    chamar(lf, "POST", "/tap", {"team": "fr", "count": 12})
    bedrock.add_client_error("converse", service_error_code="ThrottlingException")
    mover_relogio(lf, monkeypatch, 11)

    status, corpo = chamar(lf, "GET", "/state")
    assert status == 200
    assert corpo["phraseSource"] == "reserva"
    assert "Tóquio" in corpo["phrase"] and "Frankfurt" in corpo["phrase"]

    # O erro não vira uma nova tentativa imediata: o stub não tem outra resposta.
    mover_relogio(lf, monkeypatch, 15)
    depois = chamar(lf, "GET", "/state")[1]
    assert (depois["phrase"], depois["phraseSource"]) == (corpo["phrase"], "reserva")


def test_erro_generico_do_bedrock_tambem_usa_a_reserva(lf, monkeypatch, bedrock):
    largar(lf)
    bedrock.add_client_error("converse", service_error_code="AccessDeniedException")
    mover_relogio(lf, monkeypatch, 11)
    status, corpo = chamar(lf, "GET", "/state")
    assert (status, corpo["phraseSource"]) == (200, "reserva")
    assert corpo["phrase"] == lf.FRASE_SEM_TOQUES


def test_bedrock_volta_sozinho_depois_da_reserva(lf, monkeypatch, bedrock):
    largar(lf)
    bedrock.add_client_error("converse", service_error_code="ThrottlingException")
    mover_relogio(lf, monkeypatch, 11)
    assert chamar(lf, "GET", "/state")[1]["phraseSource"] == "reserva"

    bedrock.add_response("converse", resposta_bedrock("Agora é o modelo"))
    mover_relogio(lf, monkeypatch, 22)
    corpo = chamar(lf, "GET", "/state")[1]
    assert (corpo["phrase"], corpo["phraseSource"]) == ("Agora é o modelo", "bedrock")


def test_nova_rodada_limpa_a_frase_de_reserva(lf, monkeypatch, bedrock):
    largar(lf)
    bedrock.add_client_error("converse", service_error_code="ThrottlingException")
    mover_relogio(lf, monkeypatch, 11)
    assert chamar(lf, "GET", "/state")[1]["phrase"]

    chamar(lf, "POST", "/admin/reset", token=TOKEN_DE_TESTE)
    corpo = chamar(lf, "GET", "/state")[1]
    assert (corpo["phrase"], corpo["phraseSource"]) == ("", "")


def test_frase_de_reserva_empate(lf):
    item = {"sp": 40, "va": 40, "tk": 3, "fr": 0}
    assert lf.frase_de_reserva(item, INICIO) == (
        "Empate na ponta entre São Paulo e Virgínia! Cada toque agora vale ouro!"
    )


def test_frases_de_reserva_seguem_as_regras_do_locutor(lf):
    """Até 20 palavras, sem chave por preencher, com o maior placar possível."""
    item = {"sp": 123456, "va": 98765, "tk": 3, "fr": 0}
    frases = {lf.frase_de_reserva(item, INICIO + 10 * n) for n in range(len(lf.FRASES_DE_RESERVA))}
    frases |= {lf.frase_de_reserva({"sp": 5, "va": 5}, INICIO), lf.FRASE_SEM_TOQUES}

    assert len(frases) == len(lf.FRASES_DE_RESERVA) + 2
    for frase in frases:
        assert len(frase.split()) <= 20, frase
        assert "{" not in frase, frase
        assert frase.isascii() or all(ord(letra) < 0x2000 for letra in frase), frase


def test_locutor_nao_fala_com_a_rodada_parada(lf, monkeypatch, bedrock):
    largar(lf)
    mover_relogio(lf, monkeypatch, 61)
    assert chamar(lf, "GET", "/state")[1]["status"] == "finished"


# ------------------------------------------------------------------------- admin


@pytest.mark.parametrize("caminho", ["/admin/start", "/admin/reset"])
@pytest.mark.parametrize("token", [None, "", "errado", TOKEN_DE_TESTE + "x"])
def test_admin_sem_token_certo_da_401(lf, caminho, token):
    assert chamar(lf, "POST", caminho, token=token)[0] == 401
    assert chamar(lf, "GET", "/state")[1]["status"] == "waiting"


@pytest.mark.parametrize("configurado", ["", None])
def test_sem_admin_token_configurado_ninguem_entra(lf, monkeypatch, configurado):
    if configurado is None:
        monkeypatch.delenv("ADMIN_TOKEN")
    else:
        monkeypatch.setenv("ADMIN_TOKEN", configurado)
    assert chamar(lf, "POST", "/admin/start", token="qualquer")[0] == 401
    assert chamar(lf, "POST", "/admin/start")[0] == 401


def test_start_com_rodada_em_andamento_da_409_e_nao_zera(lf, monkeypatch):
    largar(lf)
    chamar(lf, "POST", "/tap", {"team": "sp", "count": 5})
    mover_relogio(lf, monkeypatch, 3)
    assert chamar(lf, "POST", "/admin/start", token=TOKEN_DE_TESTE)[0] == 409
    assert chamar(lf, "GET", "/state")[1]["scores"]["sp"] == 5


def test_novo_start_depois_do_fim_comeca_do_zero(lf, monkeypatch):
    largar(lf)
    chamar(lf, "POST", "/tap", {"team": "sp", "count": 5})
    mover_relogio(lf, monkeypatch, 61)
    assert chamar(lf, "POST", "/admin/start", token=TOKEN_DE_TESTE)[0] == 200
    _, corpo = chamar(lf, "GET", "/state")
    assert corpo["status"] == "running"
    assert corpo["secondsLeft"] == 60
    assert corpo["totalTaps"] == 0
    assert corpo["requests"] == 1


def test_reset_zera_placar_e_interrompe_a_rodada(lf):
    largar(lf)
    chamar(lf, "POST", "/tap", {"team": "sp", "count": 5})
    assert chamar(lf, "POST", "/admin/reset", token=TOKEN_DE_TESTE)[0] == 200
    _, corpo = chamar(lf, "GET", "/state")
    assert corpo["status"] == "waiting"
    assert corpo["totalTaps"] == 0
    assert corpo["requests"] == 0
