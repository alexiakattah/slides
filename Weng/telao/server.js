// Servidor do telão: entrega a página do placar e informa a URL da API.
const path = require("path");
const express = require("express");

// A mesma porta do EXPOSE no Dockerfile: é para ela que o Beanstalk encaminha o tráfego.
const PORTA = 8080;

// Tira a barra do final para a página poder montar `${API_URL}/state`.
const API_URL = (process.env.API_URL || "").replace(/\/+$/, "");

if (!API_URL) {
  console.warn("Variável API_URL não definida: o placar vai avisar na tela.");
}

const app = express();

// A página carrega este "arquivo" gerado na hora. Assim a mesma imagem Docker
// funciona com qualquer API: só muda a variável de ambiente.
// O ADMIN_TOKEN nunca passa por aqui: esta página é pública.
app.get("/config.js", (_req, res) => {
  res
    .type("application/javascript")
    .set("Cache-Control", "no-store")
    .send(`window.API_URL = ${JSON.stringify(API_URL)};\n`);
});

app.use(express.static(path.join(__dirname, "public"), { maxAge: 0 }));

app.listen(PORTA, () => {
  console.log(`Telão na porta ${PORTA}, usando a API ${API_URL || "(não definida)"}`);
});
