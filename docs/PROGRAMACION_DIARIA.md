# Programación diaria (fase 3, pendiente)

El modo diario se activará cuando el generador funcione de forma estable con voz, clips y música reales. Ya están resueltas estas piezas:

- **Comando diario:** `python -m src.main day [--date AAAA-MM-DD] --source pexels` produce todos los guiones de la cola (`data/scripts/queue/`) para esa fecha, en los dos idiomas y para las tres redes. Si un video falla, sigue con los demás y lo resume al final.
- **Idempotencia:** si el maestro de un tema está aprobado y existen sus versiones por red, esa producción se omite.
- **Reanudación barata:** la voz se cachea por frase, así que al repetir una tarea fallida solo se rehace lo que falta.
- **Registro:** `logs/studio.log`.

Pendiente: reintentos automáticos y un aviso cuando algo falle.

## Windows: Programador de tareas (borrador)

```powershell
schtasks /Create /TN "DailyPrayerStudio" /SC DAILY /ST 05:30 ^
  /TR "\"C:\ruta\daily-prayer-studio\.venv\Scripts\python.exe\" -m src.main day --source pexels" ^
  /RL LIMITED
```

En las propiedades de la tarea, fija "Iniciar en" con la carpeta del proyecto y marca "Ejecutar tanto si el usuario inició sesión como si no".

## macOS / Linux: cron (borrador)

```cron
30 5 * * * cd /ruta/daily-prayer-studio && .venv/bin/python -m src.main day --source pexels >> logs/cron.log 2>&1
```

No se presupone que Claude Code siga ejecutándose en segundo plano: la tarea programada llama directamente a Python.
