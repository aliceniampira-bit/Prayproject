# Costos y escalabilidad

> No se incluyen precios. Cambian con frecuencia y dependen de la región y del plan. Consulta siempre la página oficial indicada y anota la fecha en que la revisaste.

## Qué es gratis

| Componente | Notas |
|---|---|
| Python, FFmpeg, Pillow, pytest, espeak-ng | Software libre. El coste de cómputo es tu propio equipo. |
| API de Pexels | Gratuita con cuenta. Límite por defecto: **200 solicitudes/hora y 20 000/mes**. Se puede pedir un límite mayor. Consulta los encabezados `X-Ratelimit-Limit`, `X-Ratelimit-Remaining` y `X-Ratelimit-Reset`. Documentación: https://www.pexels.com/api/documentation/ y licencia: https://www.pexels.com/license/ |
| Fuentes Lora / Nunito | Licencia SIL OFL (Google Fonts). |
| Versículos KJV / Reina-Valera 1909 | Dominio público (la KJV tiene restricciones de Corona en el Reino Unido). |
| API de publicación de TikTok | Sin coste, pero requiere app registrada, autorización del usuario y auditoría para publicar en público. |

## Qué cuesta dinero (consulta el precio oficial)

| Servicio | Modelo de cobro habitual | Página oficial |
|---|---|---|
| ElevenLabs | Suscripción mensual con cuota de caracteres. Revisa qué planes incluyen licencia comercial. | https://elevenlabs.io/pricing |
| Azure AI Speech (voces neuronales) | Pago por caracteres sintetizados, con capa gratuita mensual. | https://azure.microsoft.com/pricing/details/cognitive-services/speech-services/ |
| Google Cloud Text-to-Speech | Pago por caracteres según el tipo de voz, con cuota gratuita. | https://cloud.google.com/text-to-speech/pricing |
| Amazon Polly | Pago por caracteres (estándar/neuronal), con capa gratuita inicial. | https://aws.amazon.com/polly/pricing/ |
| API de Claude (opcional, guiones) | Pago por tokens de entrada y salida según el modelo. | https://www.anthropic.com/pricing |
| Música con licencia | Normalmente suscripción. Verifica que cubre **uso comercial en TikTok** y cómo gestiona Content ID. | Web del proveedor elegido |

## Límites que hay que vigilar

- **Pexels:** 200 solicitudes/hora. Un video necesita de 1 a 3 búsquedas más las descargas (que se hacen desde su CDN). Con una caché de resultados, 2 videos al día quedan muy por debajo del límite.
- **Voz:** límites de caracteres por petición y de peticiones concurrentes según el proveedor. Las frases de este sistema son cortas (de 20 a 200 caracteres).
- **TikTok:** las apps no auditadas solo publican en modo privado (`SELF_ONLY`) y para un número limitado de usuarios al día.

## Recursos informáticos

- CPU moderna de 4 núcleos o más; renderizar ~80 s a 1080×1920 en H.264 `preset=medium` tarda del orden de 1 a 3 minutos. No hace falta GPU.
- RAM: 4 GB libres es suficiente.
- Disco: ~30–60 MB por video terminado, más los clips temporales. Borra `output/_work/` con regularidad.

## Cómo calcular el costo por video

```
costo_video = caracteres_narración × precio_por_carácter_TTS
            + (tokens_entrada × precio_entrada + tokens_salida × precio_salida)   # solo si usas LLM
            + suscripción_música_mensual / videos_al_mes
            + suscripción_voz_mensual / videos_al_mes                              # si el plan es mensual
```

Referencia medida con los guiones de muestra: **650–740 caracteres de narración por video**, es decir, unos 1 400 caracteres al día por los dos idiomas y unos 42 000 al mes. Multiplica por el precio vigente del proveedor.

## Cómo evitar llamadas innecesarias

- **Caché de voz por frase** (ya implementada): el audio se guarda por hash de (proveedor, voz, parámetros, texto). Volver a renderizar, cambiar la música o corregir subtítulos no genera audio nuevo.
- **Validar antes de sintetizar** (ya implementado): los guiones con errores o repetidos se rechazan antes de gastar en voz.
- **Idempotencia** (ya implementada): una fecha ya aprobada no se vuelve a producir.
- **Guiones por lotes** (opción A): redactar una semana o un mes de guiones en una sesión evita llamadas diarias al LLM.
- **Caché de búsquedas de Pexels** (fase 2) y reutilización controlada de clips mediante `media_registry.json`.
- Probar estilos con la voz local gratuita y usar la voz de pago solo para el render final.
