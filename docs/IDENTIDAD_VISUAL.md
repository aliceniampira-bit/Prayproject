# Identidad visual: `sunrise_cinematic`

Plantilla activa de la cuenta (`settings.json` → `"preset": "sunrise_cinematic"`). Todo se ajusta en `config/presets/sunrise_cinematic.json` sin tocar el código.

## Principios

| Rasgo | Cómo se consigue |
|---|---|
| Cinematográfico y contemplativo | Planos de ~7 s unidos con **fundidos de 1 s** (sin cortes bruscos ni efectos llamativos) y un **desplazamiento lento de cámara**: cada plano se amplía un 8 % y se desplaza suavemente, alternando izquierda, derecha, arriba y abajo |
| Luz natural | Búsquedas en Pexels de amaneceres, rayos de sol en el bosque, océano, nubes doradas, niebla en valles y lagos al amanecer; sin personas identificables, ciudades ni carreteras |
| Colores cálidos | Gradación suave (contraste 1,05, saturación 1,04, ligera calidez), velo oscuro del 20 % y viñeta |
| Tipografía elegante y legible | **Cormorant Garamond** para títulos y cierre, **Lora** para subtítulos (cursiva en los versículos) y **Jost** espaciada para etiquetas. Las tres tienen licencia OFL y se incluyen en el repositorio |
| Paleta | Crema `#FFF6E8` para el texto y dorado suave `#EDC98A` como acento |
| Legibilidad sin cajas | Halo oscuro difuminado bajo cada texto y un ligero oscurecimiento de la imagen mientras están en pantalla las tarjetas de título y de cierre |
| Animaciones suaves | Los textos aparecen con fundidos de 0,2 a 0,6 s; nunca rebotan ni se deslizan |

## Estructura de cada video

1. **Apertura (0–3 s):** una etiqueta pequeña en dorado ("Today's prayer", "Una oración breve"…), el título en Cormorant y una **línea dorada fina**, que es la firma visual de la cuenta. La voz empieza a los 1,2 s con el gancho, para no perder al espectador.
2. **Oración:** subtítulos de una o dos líneas en Lora, en la mitad inferior de la zona segura. Los versículos van en cursiva con su referencia encima.
3. **Cierre (3,5 s):** el nombre de la cuenta, la línea dorada y el lema del idioma. El usuario (@) no aparece porque puede cambiar de una red a otra.
4. **Portada:** el mismo diseño que la apertura sobre un fotograma del primer plano, con el título dentro del recorte central de la cuadrícula de Instagram.

## Qué la hace original

- La combinación de serif clásica, acento dorado y línea fina, repetida en la apertura, el cierre y la portada.
- La tarjeta de título coincide con la portada, así que la cuenta se reconoce en la cuadrícula del perfil.
- Cada día cambian los clips (no se repiten en 45 días), las transiciones y la dirección del movimiento.

## Personalizar

- Logotipo: `assets/branding/logo.png` (se coloca arriba a la izquierda, dentro de la zona segura).
- Colores, tamaños y posiciones: `style` en el preset.
- Búsquedas de imágenes: `settings.visual_queries` en el preset y `visual_queries` de cada tema en `themes.json`.
- La plantilla anterior (`twilight_words`, estilo del video de referencia) sigue disponible cambiando `"preset"`.
