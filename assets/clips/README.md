# Clips locales

Clips propios o con licencia. Cada clip debe describirse en `clips.json`:

```json
{"clips": [{"file": "amanecer.mp4", "title": "Amanecer", "author": "Tu nombre",
  "source_url": "", "license": "Grabación propia", "license_url": "",
  "focus_x": 0.5, "themes": ["gratitude", "hope"], "has_identifiable_people": false}]}
```

`focus_x` indica qué parte horizontal conservar al recortar a 9:16 (0 = izquierda, 1 = derecha).
Los clips con personas identificables se descartan automáticamente.
