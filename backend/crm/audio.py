"""Áudio do roteiro: conversão de gravações e TTS (edge-tts) para OGG/Opus de nota de voz."""
import asyncio
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

MAX_GRAVACAO_BYTES = 5 * 1024 * 1024
MAX_GRAVACAO_SEGUNDOS = 120
TTS_TIMEOUT_SEGUNDOS = 12


class AudioInvalido(Exception):
    pass


def _ffmpeg_para_ogg(entrada, saida, timeout):
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error", "-i", entrada, "-vn", "-ac", "1", "-ar", "48000",
         "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", saida],
        check=True, capture_output=True, timeout=timeout,
    )


def duracao_segundos(caminho):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", caminho],
        check=True, capture_output=True, timeout=15,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def converter_gravacao(arquivo):
    """Upload qualquer (webm do navegador, mp3, m4a, wav...) -> bytes OGG/Opus mono 48k, validado."""
    if arquivo.size > MAX_GRAVACAO_BYTES:
        raise AudioInvalido("Arquivo maior que 5 MB.")
    with tempfile.TemporaryDirectory() as tmp:
        entrada = os.path.join(tmp, "entrada")
        saida = os.path.join(tmp, "saida.ogg")
        with open(entrada, "wb") as f:
            for chunk in arquivo.chunks():
                f.write(chunk)
        try:
            _ffmpeg_para_ogg(entrada, saida, timeout=60)
            duracao = duracao_segundos(saida)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, KeyError, ValueError):
            raise AudioInvalido("Não foi possível ler esse arquivo de áudio.")
        if duracao > MAX_GRAVACAO_SEGUNDOS:
            raise AudioInvalido("A gravação passa de 2 minutos.")
        if duracao < 0.3:
            raise AudioInvalido("A gravação está vazia.")
        with open(saida, "rb") as f:
            return f.read()


def texto_para_fala(texto):
    """Texto renderizado do roteiro -> texto limpo para síntese (sem <br>/tags)."""
    texto = re.sub(r"<br\s*/?>", ". ", texto, flags=re.I)
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = re.sub(r"\.(\s*\.)+", ".", texto)
    return re.sub(r"\s+", " ", texto).strip()


async def _sintetizar_mp3(texto, voz, destino):
    import edge_tts
    await edge_tts.Communicate(texto, voz).save(destino)


def sintetizar(texto, voz, destino_mp3, timeout):
    asyncio.run(asyncio.wait_for(_sintetizar_mp3(texto, voz, destino_mp3), timeout=timeout))


def gerar_tts(texto, voz):
    """Gera (ou reaproveita do cache) o OGG do texto na voz dada. Devolve o caminho relativo no media."""
    falado = texto_para_fala(texto)
    if not falado:
        raise AudioInvalido("Texto vazio para TTS.")
    chave = hashlib.sha256(f"{voz}\n{falado}".encode()).hexdigest()
    relativo = f"tts/{chave}.ogg"
    if default_storage.exists(relativo):
        return relativo
    inicio = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        mp3 = os.path.join(tmp, "tts.mp3")
        ogg = os.path.join(tmp, "tts.ogg")
        sintetizar(falado, voz, mp3, timeout=TTS_TIMEOUT_SEGUNDOS)
        restante = max(1.0, TTS_TIMEOUT_SEGUNDOS - (time.monotonic() - inicio))
        _ffmpeg_para_ogg(mp3, ogg, timeout=restante)
        with open(ogg, "rb") as f:
            conteudo = f.read()
    if default_storage.exists(relativo):
        return relativo
    return default_storage.save(relativo, ContentFile(conteudo))
