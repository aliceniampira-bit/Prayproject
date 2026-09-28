"""Daily Prayer Studio command line.

Examples:
    python -m src.main check-env
    python -m src.main prepare-demo
    python -m src.main validate data/scripts/samples/*.json
    python -m src.main demo --script data/scripts/samples/2026-10-01_en_gratitude.json
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from .config import PROJECT_ROOT, ConfigError, load_settings
from .ffmpeg_utils import FFmpegError, check_tools, require_ffmpeg

log = logging.getLogger("studio")


def _setup_logging(settings, verbose: bool) -> None:
    logs = settings.path("logs_dir")
    logs.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(logs / "studio.log", encoding="utf-8")],
    )


def cmd_check_env(settings, _args) -> int:
    import os
    import platform
    print(f"Python      : {platform.python_version()} ({sys.executable})")
    for name, version in check_tools().items():
        print(f"{name:<12}: {version or 'NO INSTALADO'}")
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    print(f"espeak-ng   : {espeak or 'no instalado (solo necesario para la voz de prueba)'}")
    for mod in ("dotenv", "requests", "PIL", "pytest"):
        try:
            __import__(mod)
            print(f"{mod:<12}: ok")
        except ImportError:
            print(f"{mod:<12}: FALTA (pip install -r requirements.txt)")
    print(f".env        : {'encontrado' if (PROJECT_ROOT / '.env').exists() else 'no existe (copia .env.example)'}")
    for key in ("PEXELS_API_KEY",):
        print(f"{key:<12}: {'configurada' if os.environ.get(key) else 'no configurada'}")
    print(f"Voz         : proveedor '{settings['voice']['provider']}'")
    return 0


def cmd_prepare_demo(settings, _args) -> int:
    from .sample_assets import make_sample_assets
    require_ffmpeg()
    folder = make_sample_assets(PROJECT_ROOT / "assets" / "sample")
    print(f"Recursos de prueba creados en {folder}")
    return 0


def cmd_validate(settings, args) -> int:
    from .script_generator import PrayerScript, find_similar, iter_history, validate_script
    status = 0
    history_dirs = [settings.root / d for d in settings["script"]["history_dirs"]]
    for path in args.scripts:
        script = PrayerScript.load(Path(path))
        wpm = settings.language(script.language)["words_per_minute"]
        v = settings["video"]
        res = validate_script(script, settings.themes, wpm, v["min_duration_seconds"], v["max_duration_seconds"])
        similar = [h for h in find_similar(script, iter_history(history_dirs, script.language),
                                           settings["script"]["similarity_threshold"])
                   if Path(h["path"]).resolve() != Path(path).resolve()]
        est = script.estimated_narration_seconds(wpm) + v["lead_in_seconds"] + v["outro_seconds"]
        print(f"\n{path}\n  {script.word_count()} palabras, duración estimada del video ≈ {est:.0f}s")
        for e in res.errors:
            print(f"  ERROR: {e}")
        for s in similar:
            print(f"  ERROR: demasiado parecido a {s['id']} ({s})")
        for w in res.warnings:
            print(f"  aviso: {w}")
        if res.ok and not similar:
            print("  OK")
        else:
            status = 1
    return status


def _produce(settings, args, clip_folder: Path, music_library: Path | None) -> int:
    from .pipeline import produce
    from .publishing import write_publish_index
    from .video_sources import LocalClipSource
    require_ffmpeg()
    result = produce(Path(args.script), settings, LocalClipSource(clip_folder),
                     music_library=music_library, music_id=args.music_id, gender=args.voice,
                     srt_override=Path(args.srt) if args.srt else None, force=args.force,
                     allow_similar=args.allow_similar)
    if result.skipped:
        print(f"{result.production_id}: ya estaba aprobado en {result.folder}")
        return 0
    rep = result.report
    print(f"\n{result.production_id}: {rep.status}\nCarpeta: {result.folder}")
    for c in rep.checks:
        print(f"  [{'OK' if c.passed else 'X '}] {c.category:<11} {c.name}: {c.detail}")
    for w in rep.warnings:
        print(f"  aviso: {w}")
    write_publish_index(settings)
    return 0 if rep.approved else 2


def cmd_render(settings, args) -> int:
    lib = Path(args.music_library) if args.music_library else None
    return _produce(settings, args, Path(args.clips), lib)


def cmd_demo(settings, args) -> int:
    from .sample_assets import make_sample_assets
    require_ffmpeg()
    folder = make_sample_assets(PROJECT_ROOT / "assets" / "sample")
    return _produce(settings, args, folder / "clips", folder / "music" / "music_library.json")


def cmd_index(settings, _args) -> int:
    from .publishing import write_publish_index
    print(write_publish_index(settings))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="daily-prayer-studio", description="Daily Prayer Studio")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("check-env", help="Comprueba herramientas, dependencias y claves").set_defaults(func=cmd_check_env)
    sub.add_parser("prepare-demo", help="Genera clips y música sintéticos de prueba").set_defaults(func=cmd_prepare_demo)
    v = sub.add_parser("validate", help="Valida guiones JSON y detecta repeticiones")
    v.add_argument("scripts", nargs="+")
    v.set_defaults(func=cmd_validate)

    def production_args(sp):
        sp.add_argument("--script", required=True, help="Guion JSON")
        sp.add_argument("--voice", choices=["female", "male"], help="Sobrescribe la voz configurada")
        sp.add_argument("--music-id", help="Id de pista concreta de la biblioteca")
        sp.add_argument("--srt", help="SRT corregido manualmente para volver a renderizar")
        sp.add_argument("--force", action="store_true", help="Rehace aunque ya exista una versión aprobada")
        sp.add_argument("--allow-similar", action="store_true", help="Permite guiones parecidos a anteriores")

    d = sub.add_parser("demo", help="Prototipo: video completo con recursos sintéticos y voz local")
    production_args(d)
    d.set_defaults(func=cmd_demo)
    r = sub.add_parser("render", help="Produce un video con clips locales y la biblioteca de música")
    production_args(r)
    r.add_argument("--clips", default=str(PROJECT_ROOT / "assets" / "clips"), help="Carpeta con clips.json")
    r.add_argument("--music-library", help="Biblioteca de música alternativa")
    r.set_defaults(func=cmd_render)
    sub.add_parser("index", help="Regenera output/READY_TO_PUBLISH.md").set_defaults(func=cmd_index)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
        _setup_logging(settings, args.verbose)
        return args.func(settings, args)
    except (ConfigError, FFmpegError) as exc:
        log.error("%s", exc)
        return 1
    except Exception as exc:  # report clearly, keep the traceback in the log file
        log.exception("Error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
