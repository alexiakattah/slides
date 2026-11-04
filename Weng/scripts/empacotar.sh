#!/usr/bin/env bash
# Gera os dois zips do deploy em dist/. Não fala com a AWS.
#   dist/api.zip    código da Lambda + página do jogador
#   dist/telao.zip  projeto do telão, com o Dockerfile na raiz do zip
set -euo pipefail

raiz="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$raiz/dist"
rm -f "$raiz/dist/api.zip" "$raiz/dist/telao.zip"

(cd "$raiz/api" && zip -q -X "$raiz/dist/api.zip" lambda_function.py player.html)

# O zip é feito de dentro da pasta telao/: é isso que deixa o Dockerfile na raiz.
(cd "$raiz/telao" && zip -q -X -r "$raiz/dist/telao.zip" \
  Dockerfile .dockerignore package.json package-lock.json server.js public)

# O Beanstalk não aceitaria o Dockerfile dentro de uma pasta: confere antes de seguir.
if ! unzip -Z1 "$raiz/dist/telao.zip" | grep -x "Dockerfile" >/dev/null; then
  echo "ERRO: Dockerfile não está na raiz de dist/telao.zip" >&2
  exit 1
fi

echo "Pronto:"
ls -lh "$raiz/dist"
