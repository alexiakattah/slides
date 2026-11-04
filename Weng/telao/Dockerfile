# Imagem oficial do Node pelo espelho público da AWS: evita o limite de downloads
# anônimos do Docker Hub, que poderia travar o deploy no dia da palestra.
FROM public.ecr.aws/docker/library/node:20-alpine

WORKDIR /app

# Dependências primeiro: se só o código mudar, o Docker reaproveita esta etapa.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY server.js ./
COPY public ./public

# Não precisa de root para servir uma página.
USER node

# O Beanstalk usa o primeiro EXPOSE como a porta do container.
EXPOSE 8080

CMD ["node", "server.js"]
