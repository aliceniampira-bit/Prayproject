# Daily Prayer Studio

Sistema automatizado para producir cada día videos verticales de oraciones cristianas originales, en inglés y en español, para **TikTok, Instagram Reels y YouTube Shorts**: guion, narración con voz IA, clips de fondo, música instrumental con licencia, subtítulos sincronizados, un **video maestro** 9:16 y una **versión por red** con su título, descripción, hashtags, portada, SRT e informe de calidad, lista para revisar y publicar a mano.

> **Estado actual: prototipo multiplataforma funcional.** El sistema completo funciona de principio a fin y ya usa clips reales de Pexels. La voz (espeak, robótica) y la música de prueba están marcadas como *solo prueba*, así que el control de calidad aprueba las comprobaciones técnicas y **bloquea la publicación** a propósito hasta que elijas un proveedor de voz IA y añadas música con licencia. La publicación es manual.

---

## Producción multiplataforma

- **Maestro:** 1080×1920 (9:16), MP4, H.264 + AAC, 30 fps, configurable en `config/settings.json` → `video`.
- **Dos tipos de oración:** `short` (30–60 s) y `full` (60–90 s), en `settings.json` → `prayer_types`. La duración sale del guion y de la voz; la validación rechaza repeticiones y pausas artificiales.
- **Bilingüe:** cada tema tiene un guion en inglés y otro en español, escritos por separado. Cada uno da un video independiente con su voz, sus subtítulos y sus metadatos.
- **Tres redes:** `config/platforms.json` define carpetas, límites, zonas de interfaz, plantillas de texto y portadas. El mismo maestro se reutiliza (verificado por SHA-256) y cada red recibe sus propios metadatos y su informe.
- **Identidad visual:** plantilla `sunrise_cinematic`, cinematográfica, con luz natural, fundidos lentos, movimiento suave de cámara, Cormorant Garamond y Lora, y acento dorado ([`docs/IDENTIDAD_VISUAL.md`](docs/IDENTIDAD_VISUAL.md)).

Todo el detalle está en [`docs/MULTIPLATAFORMA.md`](docs/MULTIPLATAFORMA.md).

```
output/
  english/  _master/<fecha>_<tipo>_<tema>/   tiktok/…   instagram_reels/…   youtube_shorts/…
  spanish/  _master/…                        tiktok/…   instagram_reels/…   youtube_shorts/…
  READY_TO_PUBLISH.md
```

```bash
python -m src.main validate data/scripts/queue/*.json              # guiones + pares por idioma
python -m src.main day --date 2026-10-07 --source pexels           # 4 guiones -> 4 maestros -> 12 versiones
python -m src.main day --date 2026-10-07 --demo-assets             # igual, con recursos sintéticos
```

La plantilla anterior, `twilight_words` (inspirada en el video de referencia, [`docs/FORMATO_TWILIGHT_WORDS.md`](docs/FORMATO_TWILIGHT_WORDS.md)), sigue disponible cambiando `"preset"` en `settings.json`.

## 1. Requisitos

| Herramienta | Versión probada | Para qué |
|---|---|---|
| Python | 3.11 (compatible con 3.10 a 3.13) | Todo el sistema |
| FFmpeg + ffprobe | 6.1 (sirve cualquier versión 5.x o superior compilada con `libass` y `libx264`) | Edición, mezcla y análisis |
| espeak-ng | 1.51 | **Solo** para la voz de prueba del prototipo |
| Paquetes pip | ver `requirements.txt` | python-dotenv, requests, Pillow, fontTools, pytest |

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
# Valida los guiones de la cola y detecta repeticiones
python -m src.main validate data/scripts/queue/*.json

# Produce un video completo (maestro + 3 redes) con recursos sintéticos y voz local
python -m src.main demo --script data/scripts/queue/2026-10-07_en_hope.json
python -m src.main demo --script data/scripts/queue/2026-10-07_es_faith.json --voice male

# Pruebas automáticas (incluye un renderizado corto de extremo a extremo)
python -m pytest -q
```

Un renderizado de ~70 s tarda unos 2–3 minutos en un portátil corriente con `preset: medium`. Puedes usar `faster` o `veryfast` en `config/settings.json` para acelerar las pruebas. Las versiones por red no se vuelven a codificar (son el mismo archivo que el maestro), así que no añaden tiempo.

Con tus propios clips (carpeta `assets/clips` con su `clips.json`) y tu música (`assets/music`):

```bash
python -m src.main render --script ruta/al/guion.json [--voice female|male] [--music-id id]
```

### Revisión humana antes de publicar

1. **Guion:** léelo y cambia `"review": {"status": "approved"}`.
2. **Versículo:** compáralo con una edición fiable de la traducción indicada (KJV o Reina-Valera 1909, ambas de dominio público) y marca `"verification": {"status": "verified", "verified_by": "tu nombre", "source": "edición consultada"}`. Si no coincide, corrígelo o márcalo como `"rejected"`.
3. **Subtítulos:** si quieres corregir alguno, edita `subtitles.srt` y vuelve a renderizar con `--srt ruta/subtitles.srt --force`.
4. **Video:** míralo entero en cada red de destino. Consulta `qc_report.md` y, si existe, `NO_PUBLICAR.txt`. Nada se publica automáticamente.
5. **Al publicar:** usa `title.txt`, `description.txt` y `cover.jpg` (o el fotograma sugerido en `metadata.json`) de la carpeta de esa red. No añadas música de la app.

## 3. Arquitectura

```
guion JSON ─► validación + similitud ─► voz (frase a frase, con caché) ─► tiempos exactos por frase
                                                                               │
clips (local/Pexels) ─┐                                                        ▼
música con licencia ──┼──► FFmpeg: maestro 9:16 H.264/AAC 30 fps, fundidos, movimiento suave, color,
plantilla visual ─────┘     ASS (apertura, subtítulos, versículo, cierre), ducking, -14 LUFS, portada
                                                                               │
                          control de calidad del maestro (incluye texto medido en píxeles) ◄┘
                    técnico OK ─► output/<idioma>/_master/<fecha>_<tipo>_<tema>/
                                  └─► por red: video + título + descripción + hashtags + portada
                                      + SRT + metadata.json + control de calidad de la red
                                      ─► output/<idioma>/<red>/…  + READY_TO_PUBLISH.md
                    técnico falla ─► output/errors/<id>/ + informe (sin versiones por red)
```

Decisiones técnicas clave:

- **Síntesis frase a frase.** Cada frase se genera por separado y se une con pausas configurables. Así se conoce el instante exacto de cada frase y los subtítulos quedan sincronizados **sin reconocimiento de voz**. Funciona igual con cualquier proveedor. Cada frase se guarda en caché (`data/cache/tts/`) por hash del texto y la voz, así que repetir un render **no vuelve a pagar** la síntesis.
- **Proveedores intercambiables.** `VoiceProvider` (voz), `VideoSource` (clips) y `ScriptProvider` (guiones) son interfaces. Cambiar de proveedor supone añadir una clase, no tocar el resto del flujo.
- **Todo el texto en pantalla se renderiza con ASS/libass.** Un solo mecanismo cubre título, subtítulos, versículo en cursiva con su referencia y cierre con el nombre de la cuenta. El ancho de cada línea se mide con la fuente real (Pillow, calibrado al escalado de libass), de modo que el texto nunca se corta.
- **Zona segura común.** Cada red declara en `config/platforms.json` qué parte de la pantalla tapa su interfaz. La plantilla usa el margen más exigente de todas, y el control de calidad renderiza solo el texto y comprueba cada fotograma contra la interfaz de cada red.
- **Audio.** La voz se normaliza por su cuenta, la música se sitúa 20 dB por debajo, el *ducking* baja la música cuando hay voz y la mezcla final se normaliza a -14 LUFS con pico real ≤ -1.5 dBTP.
- **Dos niveles de control de calidad, por red.** Las comprobaciones *técnicas* (archivo, reproducción, formato y códecs, 1080×1920, 30 fps, sincronía de audio y video, sonoridad, subtítulos, texto fuera de la interfaz, portada, duración según el tipo, metadatos, procedencia, idioma, archivo sin marcas de otras apps) y las de *publicación* (música con licencia verificada para esa red, voz con uso comercial, versículo verificado, guion revisado). Solo se aprueba una versión si pasan todas.
- **Idempotencia.** Si ya existe una producción aprobada de ese tema e idioma con todas sus versiones, no se rehace (salvo con `--force`).

### Estructura

```
config/            settings.json (maestro, tipos de oración…), platforms.json (redes), visual_style.json,
                   presets/ (sunrise_cinematic, twilight_words), themes.json (12 temas)
src/
  main.py            CLI (validate, demo, render, day, export, index, check-env)
  pipeline.py        orquesta una producción (tema + idioma): maestro, portada, control de calidad
  platform_export.py versiones por red: metadatos, portada, SRT y control de calidad de cada red
  script_generator.py  modelo de guion, validación, similitud, proveedores
  voice_generator.py   proveedores de voz + ensamblado frase a frase
  subtitle_generator.py  cortes de línea, SRT y ASS
  video_editor.py      filtros FFmpeg: clips, transiciones, texto, mezcla
  music_manager.py     biblioteca con licencias y "cama" musical
  video_sources.py     interfaz de clips + clips locales
  pexels_client.py     (fase 2) Pexels, documentado pero inactivo
  quality_control.py   comprobaciones e informe
  publishing.py        índice de versiones listas y pendientes; publicación automática en fase posterior
  media_registry.py    registro de recursos usados
  style.py, ffmpeg_utils.py, sample_assets.py
assets/  music/ (+ music_library.json)  clips/ (+ clips.json)  fonts/  branding/
data/    scripts/queue/ (cola diaria)  scripts/samples/  scripts/twilight/  media_registry.json
output/  english/{_master,tiktok,instagram_reels,youtube_shorts}/  spanish/…  errors/  READY_TO_PUBLISH.md
logs/    studio.log
tests/
docs/    multiplataforma, identidad visual, costos, publicación en TikTok, programación diaria
```

Cambios respecto a la estructura propuesta: `pipeline.py` separa la orquestación de la CLI; `video_sources.py` define la interfaz común de clips (locales ahora, Pexels después); `style.py` agrupa la plantilla visual; `data/cache/` guarda la caché de voz. Los binarios con licencia (música, clips, fuentes) no se suben a git, pero sus metadatos sí.

El maestro contiene `master.mp4`, `cover.jpg`, `script.json`, `subtitles.srt`/`.ass`, `narration.json`, `credits.txt`, `provenance.json` y el informe de calidad. Cada versión por red contiene el video, `title.txt`, `description.txt`, `hashtags.txt`, `cover.jpg` (si la red permite subir portada), `subtitles.srt`, `metadata.json`, créditos, procedencia e informe de calidad.

## 4. Credenciales que vas a necesitar

| Credencial | Dónde conseguirla | Coste | Cuándo |
|---|---|---|---|
| `PEXELS_API_KEY` | https://www.pexels.com/api/ (cuenta gratuita) | Gratis | Fase 2 |
| Clave del proveedor de voz | Según el proveedor que elijas (ver abajo) | De pago por uso o suscripción | Fase 2 |
| Música con licencia | Biblioteca de música con licencia comercial para redes sociales | Normalmente suscripción | Antes de publicar |
| `ANTHROPIC_API_KEY` (opcional) | https://console.anthropic.com | De pago por uso | Solo si automatizas la escritura de guiones |
| App de TikTok for Developers | https://developers.tiktok.com | Gratis, requiere aprobación y auditoría | Fase posterior |
| App de Meta (Instagram) | https://developers.facebook.com | Gratis, requiere revisión de permisos | Fase posterior |
| Proyecto de Google Cloud (YouTube Data API) | https://console.cloud.google.com | Gratis con cuota; auditoría para videos públicos | Fase posterior |

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
- [x] **Multiplataforma:** maestro configurable, tipos corto y completo, temas bilingües, identidad `sunrise_cinematic`, versiones para TikTok, Reels y Shorts con metadatos, portada, SRT y control de calidad por red, y comando `day`.
- [ ] **Fase 2b:** proveedor de voz elegido y música con licencia real.
- [ ] **Fase 3:** programación diaria automática con reintentos (`docs/PROGRAMACION_DIARIA.md`).
- [ ] **Fase 4** (necesita apps aprobadas): publicación mediante las API oficiales, después de verificar los requisitos de cada red (`docs/MULTIPLATAFORMA.md`, `docs/PUBLICACION_TIKTOK.md`).

Costos y límites: [`docs/COSTOS_Y_ESCALABILIDAD.md`](docs/COSTOS_Y_ESCALABILIDAD.md).
