#!/usr/bin/env python3
"""Teste de carga da véspera: simula N jogadores tocando contra a API de verdade.

Só usa a biblioteca padrão do Python. ATENÇÃO: contra a URL real, isto gera requisições
pagas (cerca de N por segundo durante a rodada; centavos de dólar).

Exemplos:
    # Espera a largada dada pelo telão:
    python3 scripts/carga.py --url https://SEU-ID.execute-api.us-east-1.amazonaws.com

    # Dá a largada sozinho (lê o token da variável de ambiente, nunca da linha de comando):
    export ADMIN_TOKEN=...
    python3 scripts/carga.py --url https://... --jogadores 100 --largar

Sai com código 1 se houver erro de servidor ou se o placar não bater com os toques aceitos.
"""

import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter

TIMES = ["sp", "va", "tk", "fr"]
MAX_POR_ENVIO = 50
TEMPO_LIMITE_S = 10


def requisitar(url, metodo="GET", corpo=None, headers=None):
    """Devolve (status HTTP, corpo já lido). Status 0 significa falha de rede."""
    dados = json.dumps(corpo).encode() if corpo is not None else None
    pedido = urllib.request.Request(url, data=dados, method=metodo, headers=headers or {})
    if dados:
        pedido.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE_S) as resposta:
            return resposta.status, resposta.read()
    except urllib.error.HTTPError as erro:
        return erro.code, erro.read()
    except OSError:
        return 0, b""


class Resultados:
    """Contadores compartilhados entre as threads, protegidos por uma trava."""

    def __init__(self):
        self.trava = threading.Lock()
        self.status = Counter()
        self.latencias_ms = []
        self.toques_aceitos = Counter()

    def registrar(self, status, latencia_ms, time_id=None, toques=0):
        with self.trava:
            self.status[status] += 1
            self.latencias_ms.append(latencia_ms)
            if status == 200 and time_id:
                self.toques_aceitos[time_id] += toques


def jogador(url, fim, toques_por_segundo, resultados):
    """Igual ao celular: acumula toques e manda no máximo um POST por segundo."""
    time_id = random.choice(TIMES)
    pendentes = 0
    # Espalha os jogadores ao longo do segundo, como o atraso aleatório da página.
    time.sleep(random.random())

    while time.monotonic() < fim:
        inicio_ciclo = time.monotonic()
        pendentes += random.randint(max(1, toques_por_segundo - 2), toques_por_segundo + 2)
        count = min(pendentes, MAX_POR_ENVIO)

        inicio = time.perf_counter()
        status, _ = requisitar(f"{url}/tap", "POST", {"team": time_id, "count": count})
        latencia_ms = (time.perf_counter() - inicio) * 1000

        resultados.registrar(status, latencia_ms, time_id, count)
        if status == 200:
            pendentes -= count
        elif status == 409:
            return  # a rodada acabou

        time.sleep(max(0, 1 - (time.monotonic() - inicio_ciclo)))


def telao(url, fim, resultados):
    """Igual ao telão: consulta o placar uma vez por segundo."""
    while time.monotonic() < fim:
        inicio = time.perf_counter()
        status, _ = requisitar(f"{url}/state")
        resultados.registrar(status, (time.perf_counter() - inicio) * 1000)
        time.sleep(1)


def ler_estado(url):
    status, corpo = requisitar(f"{url}/state")
    if status != 200:
        sys.exit(f"Não consegui ler {url}/state (status {status}).")
    return json.loads(corpo)


def aguardar_largada(url, largar):
    if largar:
        token = os.environ.get("ADMIN_TOKEN", "")
        if not token:
            sys.exit("--largar exige a variável de ambiente ADMIN_TOKEN.")
        status, _ = requisitar(f"{url}/admin/start", "POST", headers={"x-admin-token": token})
        if status != 200:
            sys.exit(f"A largada falhou com status {status}.")
        return ler_estado(url)

    print("Aguardando a largada no telão (até 5 minutos)...")
    limite = time.monotonic() + 300
    while time.monotonic() < limite:
        estado = ler_estado(url)
        if estado["status"] == "running":
            return estado
        time.sleep(1)
    sys.exit("A rodada não começou em 5 minutos.")


def percentil(valores, p):
    return statistics.quantiles(valores, n=100)[p - 1] if len(valores) > 1 else valores[0]


def relatorio(resultados, estado_final):
    latencias = resultados.latencias_ms
    if not latencias:
        sys.exit("Nenhuma requisição foi feita: a rodada já tinha acabado?")

    status = resultados.status
    erros_servidor = sum(n for s, n in status.items() if s >= 500 or s == 429)
    outros_4xx = sum(n for s, n in status.items() if 400 <= s < 500 and s not in (409, 429))

    print("\n=== Resultado ===")
    print(f"Requisições feitas:      {sum(status.values())}")
    print(f"  200 OK:                {status[200]}")
    print(f"  409 fim da rodada:     {status[409]}")
    print(f"  Outros 4xx (bug):      {outros_4xx}")
    print(f"  429/5xx (limite):      {erros_servidor}")
    print(f"  Falha de rede:         {status[0]}")
    print(
        f"Latência (ms):           p50={percentil(latencias, 50):.0f}  "
        f"p95={percentil(latencias, 95):.0f}  p99={percentil(latencias, 99):.0f}  "
        f"máx={max(latencias):.0f}"
    )

    aceitos = sum(resultados.toques_aceitos.values())
    no_placar = estado_final["totalTaps"]
    print(f"Toques aceitos pela API: {aceitos}")
    print(f"Toques no placar:        {no_placar}")
    print(f"Requisições no placar:   {estado_final['requests']}")

    falhou = False
    if aceitos != no_placar:
        print("ATENÇÃO: o placar não bate com os toques aceitos.")
        print("  Se houve falha de rede, a API pode ter somado um envio sem o cliente saber.")
        falhou = True
    if erros_servidor:
        print("ATENÇÃO: houve 429/5xx. Confira a quota de concorrência da Lambda e o CloudWatch.")
        falhou = True
    if outros_4xx:
        print("ATENÇÃO: houve 4xx inesperado, provavelmente URL errada ou bug.")
        falhou = True
    if not falhou:
        print("Tudo certo: nenhum erro de servidor e o placar bate.")
    return 1 if falhou else 0


def main():
    parser = argparse.ArgumentParser(description="Simula jogadores da Corrida na Nuvem.")
    parser.add_argument("--url", required=True, help="URL base da API, sem barra no final")
    parser.add_argument("--jogadores", type=int, default=100, help="padrão: 100")
    parser.add_argument("--toques-por-segundo", type=int, default=6, help="por jogador; padrão: 6")
    parser.add_argument("--largar", action="store_true", help="dá a largada usando ADMIN_TOKEN")
    args = parser.parse_args()
    url = args.url.rstrip("/")

    estado = aguardar_largada(url, args.largar)
    segundos = estado["secondsLeft"]
    print(f"Rodada ativa, faltam {segundos} s. Soltando {args.jogadores} jogadores.")

    fim = time.monotonic() + segundos
    resultados = Resultados()
    threads = [threading.Thread(target=telao, args=(url, fim, resultados), daemon=True)]
    threads += [
        threading.Thread(
            target=jogador,
            args=(url, fim, args.toques_por_segundo, resultados),
            daemon=True,
        )
        for _ in range(args.jogadores)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Dá tempo de as últimas escritas aparecerem antes de comparar com o placar.
    time.sleep(2)
    sys.exit(relatorio(resultados, ler_estado(url)))


if __name__ == "__main__":
    main()
