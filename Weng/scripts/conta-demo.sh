#!/usr/bin/env bash
# Roda um comando usando só a conta de demo descrita no .env.
# Não altera ~/.aws nem o seu terminal: o isolamento vale apenas para este comando.
#
#   scripts/conta-demo.sh terraform -chdir=infra/terraform plan
#   scripts/conta-demo.sh aws sts get-caller-identity
set -euo pipefail

raiz="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$#" -eq 0 ]; then
  echo "Uso: scripts/conta-demo.sh <comando>" >&2
  exit 2
fi
if [ ! -f "$raiz/.env" ]; then
  echo "ERRO: crie $raiz/.env a partir de .env.example" >&2
  exit 1
fi

# Esquece qualquer credencial AWS herdada do terminal.
while IFS= read -r variavel; do
  unset "$variavel"
done < <(compgen -e | grep '^AWS_' || true)

set -a
# shellcheck disable=SC1091
source "$raiz/.env"
set +a

# Linhas vazias no .env não podem contar como credencial.
[ -n "${AWS_SESSION_TOKEN:-}" ] || unset AWS_SESSION_TOKEN

if [ -n "${AWS_PROFILE:-}" ]; then
  if [ "$AWS_PROFILE" = "default" ]; then
    echo "ERRO: o perfil default é de outro projeto. Use um perfil só para a demo." >&2
    exit 1
  fi
elif [ -n "${AWS_ACCESS_KEY_ID:-}" ] && [ -n "${AWS_SECRET_ACCESS_KEY:-}" ]; then
  # Com chaves no .env, ~/.aws fica invisível. Se as chaves falharem, o comando
  # falha também, em vez de cair silenciosamente no perfil default.
  export AWS_CONFIG_FILE=/dev/null
  export AWS_SHARED_CREDENTIALS_FILE=/dev/null
else
  echo "ERRO: o .env precisa ter AWS_PROFILE ou o par de chaves AWS." >&2
  exit 1
fi

if [ -z "${TF_VAR_conta_demo:-}" ] || [ -z "${TF_VAR_admin_token:-}" ]; then
  echo "ERRO: preencha TF_VAR_conta_demo e TF_VAR_admin_token no .env." >&2
  exit 1
fi

export AWS_REGION=us-east-1
export AWS_DEFAULT_REGION=us-east-1
export AWS_EC2_METADATA_DISABLED=true

cd "$raiz"
exec "$@"
