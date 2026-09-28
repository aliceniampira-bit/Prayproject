# Daily Prayer Studio

Sistema automatizado para producir cada día dos videos verticales (inglés y español) de oraciones cristianas originales para TikTok: guion, narración con voz IA, clips de fondo, música instrumental con licencia, subtítulos sincronizados, control de calidad y paquete listo para publicar.

> **Estado actual: fase 1, prototipo funcional.** El sistema completo funciona de principio a fin **sin ninguna clave API**. Usa recursos sintéticos (clips de degradados, un acorde de prueba y una voz local robótica) que están marcados como *solo prueba*. Por eso el control de calidad aprueba todas las comprobaciones técnicas y **bloquea la publicación** a propósito. Las integraciones con Pexels, el proveedor de voz y TikTok llegan en las fases siguientes, cuando tengas las credenciales.

---

## Formato actual: `twilight_words`

Inspirado en el video de referencia que analizamos: paisajes al atardecer con cortes secos cada ~5,5 s, texto centrado de 1–3 palabras en A Pompadour (o Jost como alternativa libre) sincronizado con la voz, la marca fija y sin tarjetas. Detalles y medidas en [`docs/FORMATO_TWILIGHT_WORDS.md`](docs/FORMATO_TWILIGHT_WORDS.md). Guiones de muestra en `data/scripts/twilight/`.

```bash
python -m src.main demo --script data/scripts/twilight/2026-10-04_es_new_beginnings.json
```

## 1. Requisitos

| Herramienta | Versión probada | Para qué |
|---|---|---|
| Python | 3.11 (compatible con 3.10 a 3.13) | Todo el sistema |
| FFmpeg + ffprobe | 6.1 (sirve cualquier versión 5.x o superior compilada con `libass` y `libx264`) | Edición, mezcla y análisis |
| espeak-ng | 1.51 | **Solo** para la voz de prueba del prototipo |
| Paquetes pip | ver `requirements.txt` | python-dotenv, requests, Pillow, pytest |

### Instalación

**Windows**
```powershell
winget install Python.Python.3.11
winget install Gyan.FFmpeg          # incluye libass y libx264
# Opcional, voz de prueba: instalador .msi de https://github.com/espeak-ng/espeak-ng/releases
```

**macOS**
```bash
brew install python@3.11 ffmpeg espeak-ng
```

**Linux (Debian/Ubuntu)**
```bash
sudo apt install python3 python3-venv ffmpeg espeak-ng
```

Después, en la carpeta del proyecto:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # en Windows: copy .env.example .env
python -m src.main check-env         # verifica herramientas, paquetes y claves
```

## 2. Uso rápido (prototipo)

**Con clips reales de Pexels** (requiere `PEXELS_API_KEY` en `.env`):

```bash
python -m src.main check-env      # prueba la clave con una búsqueda real
python -m src.main demo --source pexels --script data/scripts/twilight/2026-10-04_es_new_beginnings.json
```

Cada producción incluye `credits.txt` con el autor y la página de Pexels de cada clip.

**Solo con recursos sintéticos:**

```bash
# Valida los guiones de muestra y detecta repeticiones
python -m src.main validate data/scripts/samples/*.json

# Produce un video completo con recursos sintéticos y voz local
python -m src.main demo --script data/scripts/samples/2026-10-01_en_gratitude.json
python -m src.main demo --script data/scripts/samples/2026-10-02_es_strength.json --voice male

# Pruebas automáticas (incluye un renderizado corto de extremo a extremo)
python -m pytest -q
```

Un renderizado de ~80 s tarda unos 2 minutos en un portátil corriente con `preset: medium`. Puedes usar `faster` o `veryfast` en `config/settings.json` para acelerar las pruebas.

Con tus propios clips (carpeta `assets/clips` con su `clips.json`) y tu música (`assets/music`):

```bash
python -m src.main render --script ruta/al/guion.json [--voice female|male] [--music-id id]
```

### Revisión humana antes de publicar

1. **Guion:** léelo y cambia `"review": {"status": "approved"}`.
2. **Versículo:** compáralo con una edición fiable de la traducción indicada (KJV o Reina-Valera 1909, ambas de dominio público) y marca `"verification": {"status": "verified", "verified_by": "tu nombre", "source": "edición consultada"}`. Si no coincide, corrígelo o márcalo como `"rejected"`.
3. **Subtítulos:** si quieres corregir alguno, edita `subtitles.srt` y vuelve a renderizar con `--srt ruta/subtitles.srt --force`.
4. **Video:** míralo entero. Nada se publica automáticamente.

## 3. Arquitectura

```
guion JSON ─► validación + similitud ─► voz (frase a frase, con caché) ─► tiempos exactos por frase
                                                                               │
clips (local/Pexels) ─┐                                                        ▼
música con licencia ──┼──► FFmpeg: recorte 9:16, transiciones, corrección de color, ASS (título,
plantilla visual ─────┘     subtítulos, versículo, cierre), ducking, normalización -14 LUFS
                                                                               │
                                          control de calidad ◄─────────────────┘
                                   aprobado ─► output/<idioma>/<fecha>/ + READY_TO_PUBLISH.md
                                   fallido  ─► output/errors/<fecha>_<idioma>/ + informe
```

Decisiones técnicas clave:

- **Síntesis frase a frase.** Cada frase se genera por separado y se une con pausas configurables. Así se conoce el instante exacto de cada frase y los subtítulos quedan sincronizados **sin reconocimiento de voz**. Funciona igual con cualquier proveedor. Cada frase se guarda en caché (`data/cache/tts/`) por hash del texto y la voz, así que repetir un render **no vuelve a pagar** la síntesis.
- **Proveedores intercambiables.** `VoiceProvider` (voz), `VideoSource` (clips) y `ScriptProvider` (guiones) son interfaces. Cambiar de proveedor supone añadir una clase, no tocar el resto del flujo.
- **Todo el texto en pantalla se renderiza con ASS/libass.** Un solo mecanismo cubre título, subtítulos, versículo en cursiva con su referencia y cierre con el nombre de la cuenta. El ancho de cada línea se mide con la fuente real (Pillow, calibrado al escalado de libass), de modo que el texto nunca se corta.
- **Zona segura de TikTok.** Los márgenes (arriba 250 px, derecha 180 px por los botones, abajo 520 px por la descripción) están en `config/visual_style.json`.
- **Audio.** La voz se normaliza por su cuenta, la música se sitúa 20 dB por debajo, el *ducking* baja la música cuando hay voz y la mezcla final se normaliza a -14 LUFS con pico real ≤ -1.5 dBTP.
- **Dos niveles de control de calidad.** Las comprobaciones *técnicas* (archivo, reproducción, 1080×1920, audio, saturación, voz frente a música, subtítulos, duración, procedencia, idioma) y las de *publicación* (música con licencia verificada, voz con uso comercial, versículo verificado, guion revisado). Solo se aprueba un video si pasan todas.
- **Idempotencia.** Si ya existe una producción aprobada para esa fecha e idioma, no se rehace (salvo con `--force`).

### Estructura

```
config/            settings.json (parámetros), visual_style.json (plantilla), themes.json (12 temas)
src/
  main.py            CLI
  pipeline.py        orquesta una producción (fecha + idioma)
  script_generator.py  modelo de guion, validación, similitud, proveedores
  voice_generator.py   proveedores de voz + ensamblado frase a frase
  subtitle_generator.py  cortes de línea, SRT y ASS
  video_editor.py      filtros FFmpeg: clips, transiciones, texto, mezcla
  music_manager.py     biblioteca con licencias y "cama" musical
  video_sources.py     interfaz de clips + clips locales
  pexels_client.py     (fase 2) Pexels, documentado pero inactivo
  quality_control.py   comprobaciones e informe
  publishing.py        índice de videos listos; TikTok en fase posterior
  media_registry.py    registro de recursos usados
  style.py, ffmpeg_utils.py, sample_assets.py
assets/  music/ (+ music_library.json)  clips/ (+ clips.json)  fonts/  branding/
data/    scripts/samples/  media_registry.json
output/  english/<fecha>/  spanish/<fecha>/  errors/  READY_TO_PUBLISH.md
logs/    studio.log
tests/
docs/    costos, publicación en TikTok, programación diaria
```

Cambios respecto a la estructura propuesta: `pipeline.py` separa la orquestación de la CLI; `video_sources.py` define la interfaz común de clips (locales ahora, Pexels después); `style.py` agrupa la plantilla visual; `data/cache/` guarda la caché de voz. Los binarios con licencia (música, clips, fuentes) no se suben a git, pero sus metadatos sí.

Cada producción contiene: `video.mp4`, `script.json`, `subtitles.srt`, `description.txt`, `hashtags.txt`, `provenance.json` y `qc_report.json` + `qc_report.md`.

## 4. Credenciales que vas a necesitar

| Credencial | Dónde conseguirla | Coste | Cuándo |
|---|---|---|---|
| `PEXELS_API_KEY` | https://www.pexels.com/api/ (cuenta gratuita) | Gratis | Fase 2 |
| Clave del proveedor de voz | Según el proveedor que elijas (ver abajo) | De pago por uso o suscripción | Fase 2 |
| Música con licencia | Biblioteca de música con licencia comercial para redes sociales | Normalmente suscripción | Antes de publicar |
| `ANTHROPIC_API_KEY` (opcional) | https://console.anthropic.com | De pago por uso | Solo si automatizas la escritura de guiones |
| App de TikTok for Developers | https://developers.tiktok.com | Gratis, requiere aprobación y auditoría | Fase posterior |

Las claves van **solo** en `.env`, que está excluido de git.

## 5. Decisiones que debes tomar

1. **Proveedor de voz IA.** Opciones con voces naturales en inglés y español y términos comerciales: ElevenLabs, Azure AI Speech, Google Cloud Text-to-Speech y Amazon Polly. Compara la calidad de las voces en español (¿latino, neutro o de España?), los términos de uso comercial y el precio en su web oficial (ver `docs/COSTOS_Y_ESCALABILIDAD.md`). Mi recomendación: prueba **ElevenLabs** (voces más expresivas) y **Azure** (muy buena relación calidad/precio, voces es-MX/es-US) con uno de los guiones de muestra antes de decidir.
2. **Variante de español:** latinoamericana neutra (recomendado para TikTok) o de España.
3. **Cómo se escriben los guiones:**
   - A (recomendado al principio): lotes semanales o mensuales redactados en una sesión de Claude Code, revisados por ti y guardados en una cola. Sin coste de API y con revisión humana.
   - B: generación diaria con la API de Claude, con la misma validación y revisión.
4. **Versículos:** ¿quieres incluir uno en cada oración? Propuesta: KJV (inglés) y Reina-Valera 1909 (español), ambas de dominio público. La RVR1960 y la NVI tienen derechos de autor.
5. **Identidad:** nombre y usuario de la cuenta, logotipo, colores y tipografías (sugerencia: Lora + Nunito, licencia OFL).
6. **Fuente de música con licencia** y quién verifica cada pista.

## 6. Hoja de ruta

- [x] **Fase 1:** estructura, prototipo FFmpeg de extremo a extremo, validación de guiones, detección de similitud, subtítulos, control de calidad, pruebas y 3 temas de muestra en los dos idiomas.
- [x] **Fase 2a:** cliente de Pexels (API oficial, caché de búsquedas y descargas, filtro de personas, evita repetir clips, créditos).
- [ ] **Fase 2b:** proveedor de voz elegido y música con licencia real.
- [ ] **Fase 3:** modo diario con reanudación de tareas (`docs/PROGRAMACION_DIARIA.md`).
- [ ] **Fase 4** (necesita app aprobada): publicación en TikTok mediante la API oficial (`docs/PUBLICACION_TIKTOK.md`).

Costos y límites: [`docs/COSTOS_Y_ESCALABILIDAD.md`](docs/COSTOS_Y_ESCALABILIDAD.md).
