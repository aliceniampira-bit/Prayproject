# Tipografías

## Plantilla de la cuenta (`sunrise_cinematic`, la activa)

Incluidas en esta carpeta, con licencia SIL Open Font License (libres también para uso comercial),
descargadas del servicio oficial de Google Fonts:

| Uso | Archivo | Licencia |
|---|---|---|
| Títulos y cierre | `CormorantGaramond-SemiBold.ttf` | `CormorantGaramond-OFL.txt` |
| Subtítulos | `Lora-Medium.ttf` | `Lora-OFL.txt` |
| Versículos | `Lora-MediumItalic.ttf` | `Lora-OFL.txt` |
| Etiquetas y marca | `Jost-Regular.ttf` | `Jost-OFL.txt` |

## Plantilla base (`visual_style.json` sin preset)

La plantilla (`config/visual_style.json`) busca primero aquí:

- `Lora-Bold.ttf` y `Lora-Italic.ttf` (títulos y versículos)
- `Nunito-Bold.ttf` (subtítulos)

Ambas se distribuyen con licencia SIL Open Font License en https://fonts.google.com
(descárgalas y copia los `.ttf` en esta carpeta). Si no están, se usan fuentes del
sistema (DejaVu, Georgia/Arial…) y el informe de calidad lo indica.

El formato `twilight_words` usa **Cinzel** (incluida en esta carpeta con su licencia `Cinzel-OFL.txt`,
descargada del repositorio oficial de Google Fonts).

## Tipografía del formato `twilight_words`: A Pompadour

El formato usa **A Pompadour** (Text para el texto y Bold para los títulos). Es una fuente
**comercial**: para usarla en los videos de la cuenta necesitas la licencia de escritorio o de video
del distribuidor. Los archivos *Sample* suelen ser versiones de prueba con caracteres limitados.

Copia aquí tus archivos con licencia con uno de estos nombres (no se suben a git):
`APompadourText.otf` y `APompadourBold.otf`.

Hasta entonces se usa **Jost** (licencia OFL, libre también para uso comercial), una geométrica muy
parecida: `Jost-Regular.ttf` (peso 460) y `Jost-Bold.ttf` (peso 640), instanciadas desde la fuente
variable oficial de Google Fonts para igualar el grosor de A Pompadour. Licencia: `Jost-OFL.txt`.
