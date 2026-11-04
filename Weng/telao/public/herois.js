// Os heróis da corrida, desenhados pixel a pixel. Cada letra é uma cor da paleta
// e cada ponto é um pixel transparente. Todo sprite tem 12 colunas por 14 linhas:
// 10 do tronco, próprias de cada herói, e 4 das pernas, iguais para todos.

const HEROIS = {
  sp: {
    nome: "São Paulo",
    regiao: "sa-east-1",
    cor: "#FF9900",
    corClara: "#FFC766",
    corEscura: "#B35F00",
    tronco: [ // cavaleira de elmo
      "....kkkk....",
      "...kwwwwk...",
      "..kwwwwwwk..",
      "..kwkkkkwk..",
      "..kwskskwk..",
      "...kssssk...",
      "..kcccccck..",
      ".kcccwwccck.",
      ".kskccccksk.",
      "..kkddddkk..",
    ],
  },
  va: {
    nome: "Virgínia",
    regiao: "us-east-1",
    cor: "#00A4A6",
    corClara: "#5BE7E0",
    corEscura: "#006E70",
    tronco: [ // maga de chapéu pontudo
      ".....kk.....",
      "....kcck....",
      "...kcclck...",
      "..kccccccK..",
      ".kkkkkkkkkk.",
      "...kskskk...",
      "...kssssk...",
      "..kcclccck..",
      ".kskccccksk.",
      "..kkddddkk..",
    ],
  },
  tk: {
    nome: "Tóquio",
    regiao: "ap-northeast-1",
    cor: "#E8407F",
    corClara: "#FF93B8",
    corEscura: "#96204E",
    tronco: [ // ninja de capuz
      "...kkkkkk...",
      "..kddddddk..",
      "..kdlllldk.k",
      "..kkkkkkkkck",
      "..kskssksk.k",
      "..kddddddk..",
      "..kcccccck..",
      ".kdcccccck..",
      ".kskccccksk.",
      "..kkddddkk..",
    ],
  },
  fr: {
    nome: "Frankfurt",
    regiao: "eu-central-1",
    cor: "#7CC63D",
    corClara: "#B9EC80",
    corEscura: "#4A8020",
    tronco: [ // anã de elmo com chifres e barba
      ".k..kkkk..k.",
      "kw.kwwwwk.wk",
      "kwkwwwwwwkwk",
      ".kkkkkkkkkk.",
      "..kskssksk..",
      "..kooooook..",
      ".kcoooooock.",
      ".kccoooocck.",
      ".kskccccksk.",
      "..kkddddkk..",
    ],
  },
};

// As pernas alternam entre dois quadros: é isso que faz o herói correr.
const PERNAS_ABERTAS = [
  "..kddk.kddk.",
  "..kddk.kddk.",
  ".kbbk...kbbk",
  ".kkk.....kkk",
];
const PERNAS_JUNTAS = [
  "...kddddk...",
  "...kddddk...",
  "...kbbbbk...",
  "...kkkkkk...",
];

const COROA = [
  "o...o..o...o",
  "oo.oo..oo.oo",
  "oooooooooooo",
  "oooooooooooo",
];

const NUVEM = [
  ".....wwww.......",
  "...wwwwwwww.www.",
  "..wwwwwwwwwwwwww",
  "wwwwwwwwwwwwwwww",
  ".wwwwwwwwwwwwww.",
];

function cores(heroi) {
  return {
    k: "#1A1040", // contorno
    K: "#1A1040",
    s: "#FFD2A6", // pele
    w: "#E8ECFF", // metal
    b: "#5A4632", // botas
    o: "#FFC933", // ouro
    c: heroi ? heroi.cor : "#FFFFFF",
    l: heroi ? heroi.corClara : "#FFFFFF",
    d: heroi ? heroi.corEscura : "#FFFFFF",
  };
}

// Transforma as linhas de texto em retângulos de SVG, um por pixel.
function pixels(linhas, paleta, linhaInicial = 0) {
  let saida = "";
  linhas.forEach((linha, y) => {
    [...linha].forEach((letra, x) => {
      if (letra !== ".") {
        saida += `<rect x="${x}" y="${y + linhaInicial}" width="1" height="1" fill="${paleta[letra]}"/>`;
      }
    });
  });
  return saida;
}

function svgPixelado(largura, altura, conteudo, classe) {
  return `<svg class="${classe}" viewBox="0 0 ${largura} ${altura}" shape-rendering="crispEdges" aria-hidden="true">${conteudo}</svg>`;
}

function spriteDoHeroi(id) {
  const heroi = HEROIS[id];
  const paleta = cores(heroi);
  const conteudo =
    pixels(heroi.tronco, paleta) +
    `<g class="pernas-abertas">${pixels(PERNAS_ABERTAS, paleta, 10)}</g>` +
    `<g class="pernas-juntas">${pixels(PERNAS_JUNTAS, paleta, 10)}</g>`;
  return svgPixelado(12, 14, conteudo, "sprite");
}

function spriteDaCoroa() {
  return svgPixelado(12, 4, pixels(COROA, cores()), "coroa");
}

function spriteDaNuvem(classe) {
  return svgPixelado(16, 5, pixels(NUVEM, { w: "#FFFFFF" }), classe);
}
