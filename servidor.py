from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from threading import Thread, Lock
import json
import os
import re
import time
import shutil
import subprocess

PORTA = int(os.environ.get("PORT", "8000"))
PASTA = Path(
    os.environ.get(
        "DATA_DIR",
        str(Path(__file__).resolve().parent)
    )
).resolve()
PASTA.mkdir(parents=True, exist_ok=True)

MODELO_TEXTO = "gpt-5-mini"
MODELO_VOZ = "gpt-4o-mini-tts"
VOZ = "coral"

BITRATE_MP3 = "64k"
TAXA_AMOSTRAGEM = "24000"
CANAIS_AUDIO = "1"

geracoes_em_andamento: set[int] = set()
historias_com_erro: dict[int, str] = {}
solicitacoes_recebidas: dict[str, int] = {}

controle = Lock()


def nome_da_historia(numero: int) -> str:
    return f"historia_{numero:06d}.mp3"


def caminho_da_historia(numero: int) -> Path:
    return PASTA / nome_da_historia(numero)


def caminho_do_texto(numero: int) -> Path:
    return PASTA / f"historia_{numero:06d}.txt"


def caminho_dos_metadados(numero: int) -> Path:
    return PASTA / f"historia_{numero:06d}.json"


def obter_chave_openai() -> str:
    chave = os.environ.get("OPENAI_API_KEY", "").strip()

    if not chave:
        raise RuntimeError(
            "A variável OPENAI_API_KEY não está configurada."
        )

    return chave


def chamar_openai_json(
    endpoint: str,
    dados: dict,
    timeout: int = 120
) -> dict:
    chave = obter_chave_openai()

    corpo = json.dumps(dados).encode("utf-8")

    requisicao = Request(
        f"https://api.openai.com/v1/{endpoint}",
        data=corpo,
        method="POST",
        headers={
            "Authorization": f"Bearer {chave}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urlopen(requisicao, timeout=timeout) as resposta:
            return json.loads(
                resposta.read().decode("utf-8")
            )

    except HTTPError as erro:
        detalhe = erro.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"OpenAI respondeu HTTP {erro.code}: {detalhe}"
        ) from erro

    except URLError as erro:
        raise RuntimeError(
            f"Falha de conexão com a OpenAI: {erro}"
        ) from erro


def chamar_openai_audio(
    texto: str,
    destino: Path,
    timeout: int = 180
) -> None:
    chave = obter_chave_openai()

    dados = {
        "model": MODELO_VOZ,
        "voice": VOZ,
        "input": texto,
        "response_format": "mp3",
        "speed": 0.96,
        "instructions": (
            "Narre em português do Brasil com voz adulta, íntima, calma "
            "e natural, como alguém contando uma história perto do "
            "ouvinte. Use ritmo levemente contemplativo, pausas naturais "
            "e um toque sutil de mistério. Evite soar infantil, teatral, "
            "publicitário ou excessivamente dramático. Nos diálogos, "
            "mantenha naturalidade. Não leia títulos, marcações ou "
            "comentários; narre somente o conto."
        )
    }

    corpo = json.dumps(dados).encode("utf-8")

    requisicao = Request(
        "https://api.openai.com/v1/audio/speech",
        data=corpo,
        method="POST",
        headers={
            "Authorization": f"Bearer {chave}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urlopen(requisicao, timeout=timeout) as resposta:
            destino.write_bytes(resposta.read())

    except HTTPError as erro:
        detalhe = erro.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"OpenAI TTS respondeu HTTP {erro.code}: {detalhe}"
        ) from erro

    except URLError as erro:
        raise RuntimeError(
            f"Falha de conexão com o TTS: {erro}"
        ) from erro


def extrair_output_text(resposta: dict) -> str:
    texto_direto = resposta.get("output_text")

    if isinstance(texto_direto, str) and texto_direto.strip():
        return texto_direto.strip()

    partes: list[str] = []

    for item in resposta.get("output", []):
        if not isinstance(item, dict):
            continue

        for conteudo in item.get("content", []):
            if not isinstance(conteudo, dict):
                continue

            if conteudo.get("type") == "output_text":
                texto = conteudo.get("text", "")

                if isinstance(texto, str) and texto.strip():
                    partes.append(texto.strip())

    historia = "\n".join(partes).strip()

    if not historia:
        raise RuntimeError(
            "A resposta da OpenAI não trouxe texto utilizável."
        )

    return historia


def criar_prompt_historia(numero: int) -> str:
    return f"""
Você é um escritor especializado em contos adultos, românticos,
contemplativos e levemente misteriosos.

Escreva um conto inédito em português do Brasil para ser narrado em
áudio a um casal adulto hospedado em um refúgio romântico. Esta é a
história interna número {numero}; esse número não deve aparecer no texto.

IDENTIDADE DA EXPERIÊNCIA
- O conto deve provocar encantamento, curiosidade, intimidade,
  nostalgia, esperança ou conexão.
- O universo ficcional é inspirado em um refúgio isolado, cercado por
  natureza, bambus, jardins, montanhas, trilhas, chuva, neblina, lua,
  luzes distantes e objetos antigos.
- Use realismo mágico sutil: algo impossível pode acontecer, mas deve
  ser tratado com naturalidade.
- Cada conto deve ser completo e independente, embora locais, símbolos
  ou personagens secundários possam reaparecer ocasionalmente.

FORMA E TAMANHO
- Produza entre 3.300 e 3.950 caracteres, contando espaços.
- Mire uma narração de aproximadamente 4 a 6 minutos.
- Escreva em terceira pessoa, com linguagem adulta, acessível, elegante
  e natural.
- Use frases apropriadas para leitura em voz alta e evite períodos muito
  longos.
- Use poucos diálogos e mantenha-os curtos.
- Comece diretamente com uma situação intrigante, uma descoberta ou um
  pequeno mistério.
- Desenvolva uma escolha, uma busca, uma promessa, uma lembrança, um
  encontro, um reencontro ou uma descoberta.
- Inclua uma pequena virada que mude o significado de algo apresentado
  anteriormente.
- Termine de forma emocional, poética ou levemente aberta, deixando
  espaço para interpretação.
- Não explique a moral da história.

TOM
- Íntimo, calmo, contemplativo, romântico e levemente misterioso.
- Romantismo adulto e sutil, sem excesso de melodrama.
- Descrições sensoriais moderadas e imagens marcantes, sem exagero.

ELEMENTOS POSSÍVEIS
Você pode usar alguns destes elementos, sem precisar usar todos:
- jardim secreto, trilha entre bambus, chalé isolado ou hospedagem junto
  às montanhas;
- cartas, chaves, relógios, espelhos, fotografias ou objetos antigos;
- promessas esquecidas, escolhas não realizadas, memórias, encontros e
  reencontros;
- lugares que aparecem apenas em determinados momentos.

VARIEDADE
- Crie uma história realmente diferente das anteriores.
- Evite repetir sempre a fórmula de encontrar uma carta, voltar ao
  passado ou revelar que duas pessoas já se conheciam.
- Varie cenário, conflito emocional, elemento mágico, estrutura da
  virada e tipo de encerramento.

EVITE COMPLETAMENTE
- linguagem ou personagens infantis;
- começar com "Era uma vez";
- erotismo explícito;
- violência gráfica, terror intenso, abuso ou perigo pesado;
- traição detalhada, tragédia pesada ou morte como tema central;
- política, religião, autoajuda ou conselhos diretos de relacionamento;
- moral explícita, frases excessivamente melosas ou finais perturbadores;
- afirmar que o livro conhece, observa ou espiona quem está ouvindo;
- mencionar inteligência artificial, prompt, servidor, aplicativo ou API.

SAÍDA
- Entregue somente o texto do conto.
- Não inclua título, cabeçalho, capítulos, tópicos, Markdown, introdução,
  observações ou explicações.
- A primeira frase já deve fazer parte da narrativa.
""".strip()


def gerar_texto_historia(numero: int) -> str:
    resposta = chamar_openai_json(
        "responses",
        {
            "model": MODELO_TEXTO,
            "store": False,
            "input": criar_prompt_historia(numero)
        }
    )

    historia = extrair_output_text(resposta)

    if len(historia) > 4096:
        raise RuntimeError(
            "A história ultrapassou o limite de 4096 caracteres do TTS."
        )

    if len(historia) < 2800:
        raise RuntimeError(
            "A história gerada ficou curta demais para a experiência."
        )

    return historia


def compactar_audio_mp3(origem: Path, destino: Path) -> None:
    comando = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(origem),
        "-vn",
        "-ac", CANAIS_AUDIO,
        "-ar", TAXA_AMOSTRAGEM,
        "-af", "adelay=700,apad=pad_dur=1",
        "-b:a", BITRATE_MP3,
        "-f", "mp3",
        str(destino)
    ]

    resultado = subprocess.run(
        comando,
        capture_output=True,
        text=True
    )

    if resultado.returncode != 0:
        raise RuntimeError(
            "Falha ao compactar o áudio com ffmpeg: "
            + resultado.stderr.strip()
        )


def parece_ser_mp3(caminho: Path) -> bool:
    if not caminho.exists() or caminho.stat().st_size < 1024:
        return False

    primeiros = caminho.read_bytes()[:3]

    possui_id3 = primeiros == b"ID3"

    possui_quadro_mp3 = (
        len(primeiros) >= 2
        and primeiros[0] == 0xFF
        and (primeiros[1] & 0xE0) == 0xE0
    )

    return possui_id3 or possui_quadro_mp3


def gerar_historia_real(
    numero: int,
    solicitacao_id: str,
    dispositivo: str,
    motivo: str,
    historia_origem: int | None
) -> None:
    inicio = time.time()

    texto_temporario = (
        PASTA / f"historia_{numero:06d}.txt.tmp"
    )
    audio_original_temporario = (
        PASTA / f"historia_{numero:06d}.original.mp3.tmp"
    )
    audio_compactado_temporario = (
        PASTA / f"historia_{numero:06d}.compactado.mp3.tmp"
    )

    try:
        print(f"[IA] História {numero}: gerando texto...")

        historia = gerar_texto_historia(numero)

        texto_temporario.write_text(
            historia,
            encoding="utf-8"
        )

        print(
            f"[IA] História {numero}: texto pronto "
            f"({len(historia)} caracteres)."
        )

        print(f"[IA] História {numero}: gerando narração...")

        chamar_openai_audio(
            historia,
            audio_original_temporario
        )

        if not parece_ser_mp3(audio_original_temporario):
            raise RuntimeError(
                "O arquivo de áudio recebido não parece ser MP3."
            )

        tamanho_original = audio_original_temporario.stat().st_size

        print(
            f"[ÁUDIO] História {numero}: compactando para "
            f"{BITRATE_MP3}, mono, {TAXA_AMOSTRAGEM} Hz..."
        )

        compactar_audio_mp3(
            audio_original_temporario,
            audio_compactado_temporario
        )

        if not parece_ser_mp3(audio_compactado_temporario):
            raise RuntimeError(
                "O áudio compactado não parece ser MP3."
            )

        tamanho_compactado = audio_compactado_temporario.stat().st_size

        texto_temporario.replace(
            caminho_do_texto(numero)
        )

        audio_compactado_temporario.replace(
            caminho_da_historia(numero)
        )

        audio_original_temporario.unlink(missing_ok=True)

        duracao = round(time.time() - inicio, 2)

        metadados = {
            "numero": numero,
            "solicitacao_id": solicitacao_id,
            "dispositivo": dispositivo,
            "motivo": motivo,
            "historia_origem": historia_origem,
            "modelo_texto": MODELO_TEXTO,
            "modelo_voz": MODELO_VOZ,
            "voz": VOZ,
            "caracteres": len(historia),
            "tamanho_original_bytes": tamanho_original,
            "tamanho_mp3_bytes": tamanho_compactado,
            "bitrate_mp3": BITRATE_MP3,
            "taxa_amostragem_hz": int(TAXA_AMOSTRAGEM),
            "canais_audio": int(CANAIS_AUDIO),
            "tempo_geracao_segundos": duracao,
            "criado_em_unix": int(time.time())
        }

        caminho_dos_metadados(numero).write_text(
            json.dumps(
                metadados,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        print(
            f"[IA] História {numero} pronta: "
            f"{nome_da_historia(numero)} "
            f"({metadados['tamanho_mp3_bytes']} bytes, "
            f"{duracao}s)"
        )

    except Exception as erro:
        mensagem = str(erro)

        print(
            f"[IA] Erro na história {numero}: {mensagem}"
        )

        with controle:
            historias_com_erro[numero] = mensagem

        texto_temporario.unlink(missing_ok=True)
        audio_original_temporario.unlink(missing_ok=True)
        audio_compactado_temporario.unlink(missing_ok=True)

    finally:
        with controle:
            geracoes_em_andamento.discard(numero)


def solicitar_geracao(
    numero: int,
    solicitacao_id: str,
    dispositivo: str,
    motivo: str,
    historia_origem: int | None
) -> tuple[bool, str]:
    arquivo = caminho_da_historia(numero)

    with controle:
        numero_anterior = solicitacoes_recebidas.get(
            solicitacao_id
        )

        if numero_anterior is not None:
            return False, "solicitacao_duplicada"

        solicitacoes_recebidas[solicitacao_id] = numero

        if arquivo.exists():
            return False, "historia_ja_pronta"

        if numero in geracoes_em_andamento:
            return False, "geracao_ja_em_andamento"

        historias_com_erro.pop(numero, None)
        geracoes_em_andamento.add(numero)

    thread = Thread(
        target=gerar_historia_real,
        args=(
            numero,
            solicitacao_id,
            dispositivo,
            motivo,
            historia_origem
        ),
        daemon=True
    )
    thread.start()

    return True, "geracao_iniciada"


def enviar_arquivo_mp3(
    manipulador: SimpleHTTPRequestHandler,
    arquivo: Path
) -> None:
    tamanho = arquivo.stat().st_size

    manipulador.send_response(200)
    manipulador.send_header("Content-Type", "audio/mpeg")
    manipulador.send_header("Content-Length", str(tamanho))
    manipulador.send_header("Cache-Control", "no-store")
    manipulador.end_headers()

    with arquivo.open("rb") as origem:
        while True:
            bloco = origem.read(64 * 1024)

            if not bloco:
                break

            manipulador.wfile.write(bloco)


class ServidorLivro(SimpleHTTPRequestHandler):
    def enviar_json(
        self,
        dados: dict,
        codigo: int = 200
    ) -> None:
        corpo = json.dumps(
            dados,
            ensure_ascii=False
        ).encode("utf-8")

        self.send_response(codigo)
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8"
        )
        self.send_header(
            "Content-Length",
            str(len(corpo))
        )
        self.send_header(
            "Cache-Control",
            "no-store"
        )
        self.end_headers()
        self.wfile.write(corpo)

    def ler_json(self) -> dict | None:
        tamanho = int(
            self.headers.get("Content-Length", "0")
        )

        if tamanho <= 0:
            return None

        corpo = self.rfile.read(tamanho)

        try:
            return json.loads(
                corpo.decode("utf-8")
            )
        except json.JSONDecodeError:
            return None

    def do_GET(self) -> None:
        caminho = urlparse(self.path).path

        if caminho == "/":
            self.enviar_json({
                "servico": "livro-magico",
                "status": "online"
            })
            return

        if caminho == "/health":
            self.enviar_json({
                "status": "ok",
                "servico": "livro-magico",
                "porta": PORTA,
                "data_dir": str(PASTA)
            })
            return

        if caminho == "/data" or caminho.startswith("/data/"):
            self.enviar_json({
                "erro": "Acesso não permitido."
            }, 403)
            return

        arquivo_mp3 = re.fullmatch(
            r"/(historia_\d{6}\.mp3)",
            caminho
        )

        if arquivo_mp3:
            arquivo = PASTA / arquivo_mp3.group(1)

            if not arquivo.exists():
                self.send_error(404, "História não encontrada.")
                return

            enviar_arquivo_mp3(self, arquivo)
            return

        correspondencia = re.fullmatch(
            r"/api/historias/(\d+)/status",
            caminho
        )

        if correspondencia:
            numero = int(correspondencia.group(1))
            arquivo = caminho_da_historia(numero)

            if arquivo.exists():
                host = self.headers.get(
                    "Host",
                    f"localhost:{PORTA}"
                )

                self.enviar_json({
                    "numero": numero,
                    "status": "pronta",
                    "url": (
                        f"http://{host}/"
                        f"{nome_da_historia(numero)}"
                    ),
                    "tamanho_bytes": arquivo.stat().st_size
                })
                return

            with controle:
                erro = historias_com_erro.get(numero)
                esta_gerando = numero in geracoes_em_andamento

            if erro:
                self.enviar_json({
                    "numero": numero,
                    "status": "erro",
                    "url": None,
                    "mensagem": erro
                })
                return

            self.enviar_json({
                "numero": numero,
                "status": (
                    "gerando"
                    if esta_gerando
                    else "aguardando"
                ),
                "url": None
            })
            return

        super().do_GET()

    def do_POST(self) -> None:
        caminho = urlparse(self.path).path

        if caminho != "/api/historias/gerar":
            self.enviar_json({
                "erro": "Endpoint não encontrado."
            }, 404)
            return

        dados = self.ler_json()

        if dados is None:
            self.enviar_json({
                "erro": "JSON inválido."
            }, 400)
            return

        numero = dados.get("numero")
        solicitacao_id = dados.get("solicitacao_id")
        dispositivo = dados.get(
            "dispositivo",
            "desconhecido"
        )
        motivo = dados.get(
            "motivo",
            "não_informado"
        )
        historia_origem = dados.get(
            "historia_origem"
        )

        if not isinstance(numero, int) or numero <= 0:
            self.enviar_json({
                "erro": "numero precisa ser um inteiro positivo."
            }, 400)
            return

        if (
            not isinstance(solicitacao_id, str)
            or not solicitacao_id.strip()
        ):
            self.enviar_json({
                "erro": "solicitacao_id é obrigatório."
            }, 400)
            return

        iniciou, resultado = solicitar_geracao(
            numero,
            solicitacao_id,
            dispositivo,
            motivo,
            historia_origem
        )

        print(
            f"[SOLICITAÇÃO] dispositivo={dispositivo} "
            f"numero={numero} "
            f"origem={historia_origem} "
            f"motivo={motivo} "
            f"id={solicitacao_id} "
            f"resultado={resultado}"
        )

        self.enviar_json({
            "recebido": True,
            "numero": numero,
            "solicitacao_id": solicitacao_id,
            "geracao_iniciada": iniciou,
            "resultado": resultado,
            "status": (
                "gerando"
                if iniciou
                else resultado
            )
        })


if __name__ == "__main__":
    try:
        obter_chave_openai()
    except RuntimeError as erro:
        print()
        print(f"ERRO DE CONFIGURAÇÃO: {erro}")
        print()
        print(
            'No Terminal, execute: '
            'export OPENAI_API_KEY="sua-chave-aqui"'
        )
        raise SystemExit(1)

    if shutil.which("ffmpeg") is None:
        print()
        print("ERRO DE CONFIGURAÇÃO: ffmpeg não encontrado.")
        print("No Mac, instale com: brew install ffmpeg")
        raise SystemExit(1)

    host = os.environ.get("HOST", "0.0.0.0")

    servidor = ThreadingHTTPServer(
        (host, PORTA),
        ServidorLivro
    )

    print(
        f"Servidor real do Livro Mágico em {host}:{PORTA}"
    )
    print(f"Pasta persistente: {PASTA}")
    print(f"Modelo de texto: {MODELO_TEXTO}")
    print(f"Modelo de voz: {MODELO_VOZ}")
    print(f"Voz: {VOZ}")
    print(
        f"Áudio final: {BITRATE_MP3}, mono, "
        f"{TAXA_AMOSTRAGEM} Hz"
    )
    print("Endpoint: POST /api/historias/gerar")
    print("Pressione Ctrl+C para encerrar.")

    servidor.serve_forever()
