# Producción multiplataforma: TikTok, Instagram Reels y YouTube Shorts

Un tema produce **dos videos independientes** (inglés y español). Cada video tiene **un maestro vertical** y **tres versiones** (una por red), cada una con sus propios metadatos y su informe de calidad.

```
guion EN ─┐                              ┌─ output/english/tiktok/<fecha>_<tipo>_<tema>/
          ├─► maestro EN (_master) ──────┼─ output/english/instagram_reels/…
tema ─────┤                              └─ output/english/youtube_shorts/…
          ├─► maestro ES (_master) ──────┬─ output/spanish/tiktok/…
guion ES ─┘                              ├─ output/spanish/instagram_reels/…
                                         └─ output/spanish/youtube_shorts/…
```

## 1. Video maestro

Se define en `config/settings.json` → `video` y se puede cambiar sin tocar el código:

| Parámetro | Valor inicial |
|---|---|
| Resolución / relación | 1080 × 1920, 9:16, vertical |
| Contenedor | MP4 (`+faststart`, para que empiece a reproducirse antes de descargarse entero) |
| Video | H.264 (`libx264`), perfil High, nivel 4.2, `yuv420p`, CRF 20 |
| Audio | AAC, 192 kb/s, 48 kHz, -14 LUFS, pico real ≤ -1,5 dBTP |
| Fotogramas | 30 fps |
| Metadatos | Se eliminan los que vienen de los clips de origen (`-map_metadata -1`) |

**¿Por qué el mismo archivo sirve para las tres redes?** Las tres aceptan este formato de forma nativa y lo recodifican al subirlo. Un único maestro evita pérdidas por una doble compresión y garantiza que las tres versiones son idénticas; la verificación usa SHA-256. Las versiones por red son *enlaces duros* al maestro, así que no ocupan espacio adicional. Si una red necesitara otra codificación, se indica en `platforms.json` → `video.transcode` (por ejemplo `{"crf": 18}`) y solo esa versión se recodifica desde el maestro.

## 2. Tipos de oración y duración

Se definen en `settings.json` → `prayer_types` y cada guion indica su `type`:

| Tipo | Duración total | Estructura | Versículo |
|---|---|---|---|
| `short` | 30–60 s | gancho que conecta enseguida, oración breve de 1 o 2 párrafos (gratitud, fe, paz, esperanza), cierre que invita a reflexionar | No |
| `full` | 60–90 s | introducción breve, versículo opcional, oración desarrollada con tono cálido, cierre reflexivo | Opcional |

**Nada de relleno.** La duración sale del guion y del ritmo natural de la voz: el sistema no estira el audio, no añade silencios y no repite frases. La validación **rechaza** los guiones con frases repetidas (de 3 palabras o más) o con marcas de pausa artificial (`.....`, `[pausa]`, `<break>`). Si un guion queda corto para su tipo, el aviso pide escribir más contenido o cambiar el tipo.

**TikTok Creator Rewards.** El informe de TikTok de una oración `full` avisa (sin bloquear) si el video no supera 60 s. Los requisitos del programa (duración, originalidad, edad, seguidores, visualizaciones, países) cambian: revísalos en la fuente oficial antes de contar con ellos.

## 3. Producción bilingüe

- Cada tema tiene un guion por idioma, con la misma fecha, tipo y tema (`data/scripts/queue/<fecha>_<en|es>_<tema>.json`). `validate` agrupa los guiones por tema y avisa si falta un idioma.
- Los dos guiones **se escriben por separado** para su público; no son traducciones línea a línea. Los de muestra lo demuestran: el título, el gancho, las imágenes y el número de párrafos cambian entre idiomas. `validate` avisa cuando dos versiones tienen la misma estructura y longitudes casi idénticas, que es una señal típica de traducción literal.
- Voz: cada idioma tiene su propia voz en `settings.json` → `voice.voices`.
- Subtítulos, título, descripción y hashtags salen del guion de ese idioma, y el control de calidad comprueba que estén en el idioma correcto.

## 4. Metadatos por red

Se generan automáticamente a partir del guion (`title`, `description`, `hashtags`) y de las reglas de `config/platforms.json`:

| | TikTok | Instagram Reels | YouTube Shorts |
|---|---|---|---|
| Título | No hay campo de título; `title.txt` guarda el texto de apertura que aparece en pantalla | Igual que TikTok; el pie de foto empieza con el título | `{título} \| {tipo}` (máx. 100 caracteres) |
| Texto | descripción + hashtags | título + descripción + hashtags | descripción + créditos + hashtags |
| Hashtags | máx. 5 (criterio editorial) | máx. 5 | máx. 5 |
| Portada | `cover.jpg` (subir) o el fotograma sugerido | `cover.jpg`, con el título dentro del recorte de la cuadrícula del perfil | fotograma sugerido (tarjeta de título) |
| SRT | archivo de referencia | archivo de referencia | se puede subir en YouTube Studio |

Si quieres un texto concreto para una red, añádelo en el guion:

```json
"platform_overrides": {
  "youtube_shorts": {"title": "A Prayer for Faith When You Can't See the Way"},
  "instagram_reels": {"hashtags": ["#prayer", "#faith", "#reelsprayer"]}
}
```

## 5. Zona segura

Cada red tapa partes distintas de la pantalla (pestañas arriba, botones a la derecha, descripción y controles abajo). `platforms.json` → `ui_overlay` guarda esos márgenes para cada red. **Al cargar la configuración, la zona segura de la plantilla se amplía con el margen más exigente de las redes activadas**, así el mismo maestro sirve para las tres.

El control de calidad no confía solo en los cálculos del diseño: **renderiza la capa de texto sobre negro** (6 fotogramas por segundo), mide dónde caen los píxeles de texto y comprueba cada fotograma contra la zona libre de cada red. El informe indica el instante y la caja de cualquier texto que invada la interfaz.

Las medidas iniciales son aproximaciones. Para ajustarlas: publica un video privado de prueba en cada red, haz capturas en tu teléfono y corrige `ui_overlay`.

## 6. Archivos de cada versión

| Archivo | Contenido |
|---|---|
| `<fecha>_<tipo>_<tema>_<idioma>_<red>.mp4` | Video (idéntico al maestro salvo que se configure otra codificación) |
| `title.txt` | Título (YouTube) o texto de apertura (TikTok e Instagram) |
| `description.txt` | Texto completo para pegar al publicar, con hashtags |
| `hashtags.txt` | Hashtags, uno por línea |
| `cover.jpg` | Portada 1080×1920, si la red permite subirla |
| `subtitles.srt` | Subtítulos sincronizados |
| `metadata.json` | Todo lo anterior, con el fotograma sugerido como portada, notas de publicación y fuentes oficiales |
| `credits.txt`, `provenance.json` | Autor, licencia y origen de cada recurso |
| `qc_report.json` / `qc_report.md` | Informe de calidad completo (maestro + red) |
| `NO_PUBLICAR.txt` | Solo si falta algo, con qué hay que resolver |

`output/READY_TO_PUBLISH.md` lista las versiones listas y las pendientes.

## 7. Control de calidad

Un video solo queda marcado como terminado (`approved`) si pasa **todas** las comprobaciones de su red:

- **Archivo:** reproducción completa sin errores, MP4 con H.264 `yuv420p` y AAC, 1080×1920 vertical y sin rotación, 30 fps, y pistas de audio y video de la misma duración.
- **Sincronía:** la voz, la música y el video cubren exactamente la misma duración; los subtítulos siguen los tiempos reales de cada frase, sin solapamientos ni texto fuera del video; el SRT de cada red coincide con el del maestro.
- **Audio:** hay narración, el volumen es correcto, no hay saturación y la música queda al menos 10 dB por debajo de la voz.
- **Texto:** no queda tapado por la interfaz de esa red (medido sobre los píxeles reales), cabe en pantalla y la portada conserva el título dentro de los recortes de la cuadrícula del perfil.
- **Duración:** dentro del rango de su tipo y del límite de la red.
- **Metadatos:** título y texto dentro de los límites, hashtags válidos y sin repetir, y todo en el idioma del video.
- **Archivo limpio:** ningún clip procede de TikTok, Instagram o YouTube (que llevarían su marca de agua), el archivo no lleva etiquetas de otras apps y la única superposición es el texto propio.
- **Procedencia:** licencia y autor de cada clip, pista y voz.
- **Publicación:** música verificada **para esa red**, voz IA con licencia comercial, versículo verificado y guion aprobado por una persona.

## 8. Música

- La música se mezcla en el maestro y debe tener licencia comercial para **cada** red de destino: `music_library.json` → `platforms_verified`.
- **Nunca** se añade música nativa de las apps (sonidos de TikTok, audio de Instagram…) al archivo. Tampoco la añadas al publicar: el video ya lleva su música y se duplicaría el audio.
- Si la licencia exige atribución, escríbela en `attribution` y se añade a las descripciones.
- Si la pista está registrada en Content ID (`content_id_registered`), el informe de YouTube lo advierte.

## 9. Publicación

**Por ahora, la publicación es manual.** Revisa cada video completo, `qc_report.md` y el texto antes de subirlo.

Antes de automatizarla hay que verificar las condiciones oficiales vigentes de cada red:

| Red | Vía oficial | Puntos a verificar |
|---|---|---|
| TikTok | Content Posting API (subida a borradores con `video.upload`, o Direct Post con `video.publish`) | App registrada, OAuth del propietario, auditoría para publicar en público. Ver `PUBLICACION_TIKTOK.md` |
| Instagram | API de publicación de contenido de Instagram Platform (`media_type=REELS`) | Cuenta profesional, app de Meta con permisos revisados, límite diario de publicaciones por API, video en una URL pública |
| YouTube | YouTube Data API v3, `videos.insert` | Proyecto de Google Cloud con OAuth; los videos que suben proyectos no verificados (creados después del 28 de julio de 2020) quedan privados hasta superar una auditoría; cuota diaria de la API |

Cuando los hayas revisado, apunta la fecha en `platforms.json` → `last_reviewed` de cada red (`check-env` la muestra).

## 10. Uso

```bash
# Valida los guiones de la cola, comprueba que cada tema tenga los dos idiomas
python -m src.main validate data/scripts/queue/*.json

# Produce todo lo de una fecha: cada guion -> maestro + 3 redes
python -m src.main day --date 2026-10-07 --source pexels

# Un solo guion, solo para algunas redes
python -m src.main render --script data/scripts/queue/2026-10-07_es_hope.json --source pexels \
    --platforms tiktok,youtube_shorts

# Rehace las carpetas por red desde un maestro (tras cambiar platforms.json), sin volver a renderizar
python -m src.main export output/spanish/_master/2026-10-07_short_hope
```
