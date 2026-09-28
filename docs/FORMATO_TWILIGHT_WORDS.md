# Formato `twilight_words`: análisis del video de referencia

Referencia: el video de TikTok de @amorinfinitoadios que compartiste (55,5 s). Se ha analizado solo para extraer el **formato**. No se ha copiado su texto, su música, sus imágenes ni su marca.

## Qué se midió

| Aspecto | Referencia | Cómo lo reproduce el formato |
|---|---|---|
| Duración | 55,5 s | Rango 45–70 s; guiones de 105–125 palabras (57–65 s estimados) |
| Edición | 10 planos, **cortes secos** cada ~5,5 s (cortes en 5,0 / 17,6 / 18,7 / 25,5 / 31,0 / 36,1 / 41,8 / 47,2 / 49,1 s) | `transition: cut`, `target_clip_seconds: 5.5` |
| Imagen | Paisajes al atardecer o de noche: carreteras, caminos mojados, montañas con luces de ciudad, trigo, árboles a contraluz, bosque con niebla. Gradación oscura y cálida | `visual_queries` para Pexels, gradación con contraste alto, viñeta y ligera calidez |
| Texto | Serif clásica en mayúsculas (tipo Cinzel), color crema, sin contorno, sombra suave, **centrado al 50 % de la altura**, 1–3 palabras cada 0,5–0,8 s con fundido de entrada corto | `subtitles.mode: word_groups`, `words_center_y: 980`. **Tipografía elegida por ti: A Pompadour** (geométrica, en mayúsculas y minúsculas); mientras no esté instalada se usa Jost |
| Marca | Nombre de la cuenta pequeño y fijo en versalitas, al 70 % de la altura | `brand_text` (usa **tu** nombre de cuenta), `brand_center_y: 1330` |
| Tarjetas | Sin título ni cierre; empieza directamente con la oración | `title_card_seconds: 0`, `closing_card: false` |
| Audio | Narración hablada (se ven sibilantes y pausas en el espectrograma) sobre un fondo ambiental sostenido (piano o pad). Mezcla muy comprimida: -8,3 LUFS, rango de 2,3 LU | Voz a ~150 palabras/min con pausas cortas; música 13 dB por debajo de la voz, con *ducking*; salida a -14 LUFS (el nivel que TikTok normaliza) |
| Guion | Oración de mañana en primera persona: invocación, gratitud por el día, entrega de lo difícil, petición de guía y de cuidar las palabras, confianza, amén. Sin versículo | Misma estructura en `data/scripts/twilight/` con texto original |

## Estructura de guion del formato

1. **Invocación con gancho** (`hook`): una frase que nombra a Dios y sitúa el momento ("antes de mirar el teléfono…").
2. **Gratitud** concreta por el día o por las personas.
3. **Entrega**: lo difícil, lo pendiente, lo que preocupa.
4. **Petición**: guía, palabras, paciencia, protección.
5. **Confianza**: una frase corta y firme.
6. **Cierre** (`closing`): "En el nombre de Jesús, amén." / "In Jesus' name, amen."

## Música para este formato

Busca en tu biblioteca con licencia: *ambient piano*, *cinematic piano pad*, *worship ambient*, *soft atmospheric*, entre 60 y 80 BPM, sin voces y sin percusión marcada. No uses el sonido del video de referencia salvo que lo añadas desde la propia app de TikTok y su biblioteca comercial lo permita para tu tipo de cuenta.

## Cambiar de formato

`config/settings.json` → `"preset": "twilight_words"` (el actual). Pon `"preset": null` para volver al formato original, con título, subtítulos abajo, fundidos y tarjeta de cierre.
