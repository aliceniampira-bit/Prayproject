# Programación diaria (fase 3, pendiente)

El modo diario se activará cuando el generador funcione de forma estable con voz, clips y música reales. Ya están resueltas estas piezas:

- **Idempotencia:** si `output/<idioma>/<fecha>/qc_report.json` está aprobado, esa producción se omite.
- **Reanudación barata:** la voz se cachea por frase, así que al repetir una tarea fallida solo se rehace lo que falta.
- **Registro:** `logs/studio.log`.

Pendiente de implementar: el comando `python -m src.main daily [--date AAAA-MM-DD]`, que tomará el guion de la cola para la fecha, producirá los dos idiomas, reintentará lo fallido y escribirá un resumen.

## Windows: Programador de tareas (borrador)

```powershell
schtasks /Create /TN "DailyPrayerStudio" /SC DAILY /ST 05:30 ^
  /TR "\"C:\ruta\daily-prayer-studio\.venv\Scripts\python.exe\" -m src.main daily" ^
  /RL LIMITED
```

En las propiedades de la tarea, fija "Iniciar en" con la carpeta del proyecto y marca "Ejecutar tanto si el usuario inició sesión como si no".

## macOS / Linux: cron (borrador)

```cron
30 5 * * * cd /ruta/daily-prayer-studio && .venv/bin/python -m src.main daily >> logs/cron.log 2>&1
```

No se presupone que Claude Code siga ejecutándose en segundo plano: la tarea programada llama directamente a Python.
