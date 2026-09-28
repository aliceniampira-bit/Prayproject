"""Daily Prayer Studio command line.

Examples:
    python -m src.main check-env
    python -m src.main validate data/scripts/queue/*.json
    python -m src.main demo --script data/scripts/queue/2026-10-07_es_hope.json
    python -m src.main day --date 2026-10-07 --demo-assets
    python -m src.main export output/spanish/_master/2026-10-07_short_hope
"""

from __future__ import annotations

import argparse
import json
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
    if os.environ.get("PEXELS_API_KEY"):
        from .pexels_client import PexelsError, PexelsVideoSource
        try:
            source = PexelsVideoSource(settings)
            source.search("sunset", 1)
            print(f"Pexels      : clave válida, conexión correcta "
                  f"(quedan {source.rate_limit.get('X-Ratelimit-Remaining', '?')} solicitudes este mes)")
        except PexelsError as exc:
            print(f"Pexels      : clave configurada, pero la prueba falló: {exc}")
    else:
        print("Pexels      : PEXELS_API_KEY no configurada")
    print(f"Voz         : proveedor '{settings['voice']['provider']}'")
    v = settings["video"]
    print(f"Maestro     : {v['width']}x{v['height']} ({v.get('aspect_ratio')}), {v['fps']} fps, "
          f"{v.get('container', 'mp4').upper()} {v.get('video_codec')}/{v.get('audio_codec')}")
    print(f"Plantilla   : {settings.get('preset')}")
    for name in settings.enabled_platforms():
        cfg = settings.platform(name)
        print(f"Red         : {cfg.get('label', name):<16} carpeta '{cfg.get('folder', name)}', "
              f"reglas revisadas: {cfg.get('last_reviewed') or 'pendiente (ver docs/MULTIPLATAFORMA.md)'}")
    return 0


def cmd_prepare_demo(settings, _args) -> int:
    from .sample_assets import make_sample_assets
    require_ffmpeg()
    folder = make_sample_assets(PROJECT_ROOT / "assets" / "sample")
    print(f"Recursos de prueba creados en {folder}")
    return 0


def cmd_validate(settings, args) -> int:
    from .script_generator import (PrayerScript, estimated_video_seconds, find_similar, iter_history,
                                   literal_translation_suspects, pair_by_topic, validate_with_settings)
    status = 0
    history_dirs = [settings.root / d for d in settings["script"]["history_dirs"]]
    loaded = []
    for path in args.scripts:
        script = PrayerScript.from_dict(json.loads(Path(path).read_text(encoding="utf-8")),
                                        default_type=settings.get("default_prayer_type", "full"))
        loaded.append((Path(path), script))
        res = validate_with_settings(script, settings)
        similar = [h for h in find_similar(script, iter_history(history_dirs, script.language),
                                           settings["script"]["similarity_threshold"])
                   if Path(h["path"]).resolve() != Path(path).resolve()]
        t = settings.prayer_type(script.type) if script.type in settings["prayer_types"] else {}
        print(f"\n{path}\n  {script.type} · {script.word_count()} palabras · duración estimada ≈ "
              f"{estimated_video_seconds(script, settings):.0f}s (rango {t.get('min_seconds')}-{t.get('max_seconds')}s)")
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
    by_path = dict(loaded)
    languages = list(settings["languages"])
    print("\nTemas (cada tema debe tener una versión por idioma):")
    for topic, versions in sorted(pair_by_topic(loaded).items()):
        missing = [lang for lang in languages if lang not in versions]
        print(f"  {topic}: {', '.join(sorted(versions))}" + (f" — falta {', '.join(missing)}" if missing else ""))
        if len(versions) == 2:
            a, b = (by_path[versions[lang]] for lang in sorted(versions))
            for note in literal_translation_suspects(a, b):
                print(f"    aviso: {note}")
    return status


def _platforms(settings, args) -> list[str] | None:
    if not getattr(args, "platforms", None):
        return None
    chosen = [p.strip() for p in args.platforms.split(",") if p.strip()]
    for p in chosen:
        settings.platform(p)  # raises a clear error for unknown names
    return chosen


def _print_result(result) -> bool:
    if result.skipped:
        print(f"{result.production_id}: ya estaba aprobado en {result.folder}")
        return True
    rep = result.report
    print(f"\n{result.production_id}: maestro {rep.status}\nCarpeta: {result.folder}")
    for c in rep.checks:
        print(f"  [{'OK' if c.passed else 'X '}] {c.category:<11} {c.name}: {c.detail}")
    for w in rep.warnings:
        print(f"  aviso: {w}")
    for ex in result.exports:
        failed = [c.name for c in ex.report.checks if not c.passed]
        print(f"  -> {ex.platform:<16} {ex.report.status:<24} {ex.folder}"
              + (f"\n     pendiente: {', '.join(failed)}" if failed else ""))
    return rep.approved and all(ex.report.approved for ex in result.exports)


def _clip_source(settings, args, clip_folder: Path):
    if getattr(args, "source", "local") == "pexels":
        from .pexels_client import PexelsVideoSource
        return PexelsVideoSource(settings)
    from .video_sources import LocalClipSource
    return LocalClipSource(clip_folder)


def _produce(settings, args, clip_folder: Path, music_library: Path | None) -> int:
    from .pipeline import produce
    from .publishing import write_publish_index
    require_ffmpeg()
    result = produce(Path(args.script), settings, _clip_source(settings, args, clip_folder),
                     music_library=music_library, music_id=args.music_id, gender=args.voice,
                     srt_override=Path(args.srt) if args.srt else None, force=args.force,
                     allow_similar=args.allow_similar, platforms=_platforms(settings, args))
    approved = _print_result(result)
    write_publish_index(settings)
    return 0 if approved else 2


def cmd_render(settings, args) -> int:
    lib = Path(args.music_library) if args.music_library else None
    return _produce(settings, args, Path(args.clips), lib)


def cmd_demo(settings, args) -> int:
    from .sample_assets import make_sample_assets
    require_ffmpeg()
    folder = make_sample_assets(PROJECT_ROOT / "assets" / "sample")
    return _produce(settings, args, folder / "clips", folder / "music" / "music_library.json")


def cmd_day(settings, args) -> int:
    """Every script queued for a date (both languages, every topic), each exported to every network."""
    import datetime

    from .pipeline import ProductionError, produce
    from .publishing import write_publish_index
    from .script_generator import PrayerScript, pair_by_topic
    require_ffmpeg()
    day = args.date or datetime.date.today().isoformat()
    queue = Path(args.queue)
    paths = sorted(queue.glob(f"{day}_*.json"))
    if not paths:
        print(f"No hay guiones para {day} en {queue}")
        return 1
    default_type = settings.get("default_prayer_type", "full")
    scripts = [(p, PrayerScript.from_dict(json.loads(p.read_text(encoding="utf-8")), default_type)) for p in paths]
    for topic, versions in pair_by_topic(scripts).items():
        missing = [lang for lang in settings["languages"] if lang not in versions]
        if missing:
            print(f"aviso: el tema {topic} no tiene versión en {', '.join(missing)}")
    if args.demo_assets:
        from .sample_assets import make_sample_assets
        folder = make_sample_assets(PROJECT_ROOT / "assets" / "sample")
        clip_folder, library = folder / "clips", folder / "music" / "music_library.json"
    else:
        clip_folder = Path(args.clips)
        library = Path(args.music_library) if args.music_library else None
    source = _clip_source(settings, args, clip_folder)
    ok, failed = 0, []
    for path, _ in scripts:
        try:
            result = produce(path, settings, source, music_library=library, force=args.force,
                             allow_similar=args.allow_similar, platforms=_platforms(settings, args))
        except (ProductionError, RuntimeError) as exc:  # keep going with the other videos
            log.error("%s: %s", path.name, exc)
            failed.append(path.name)
            continue
        ok += _print_result(result)
    print(f"\nIndex: {write_publish_index(settings)}")
    print(f"{day}: {len(scripts)} videos, {ok} listos para publicar, {len(failed)} con error"
          + (f" ({', '.join(failed)})" if failed else ""))
    return 0 if not failed else 1


def cmd_export(settings, args) -> int:
    """Rebuild the per-network folders from an existing master (e.g. after editing platforms.json)."""
    from .platform_export import export_all
    from .publishing import write_publish_index
    master = Path(args.master)
    if not (master / "master.mp4").exists():
        print(f"No hay master.mp4 en {master}")
        return 1
    results = export_all(master, settings, _platforms(settings, args))
    for ex in results:
        failed = [c.name for c in ex.report.checks if not c.passed]
        print(f"{ex.platform:<16} {ex.report.status:<24} {ex.folder}"
              + (f"\n  pendiente: {', '.join(failed)}" if failed else ""))
    write_publish_index(settings)
    return 0 if all(ex.report.approved for ex in results) else 2


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
        sp.add_argument("--source", choices=["local", "pexels"], default="local",
                        help="Origen de los clips de fondo (pexels requiere PEXELS_API_KEY)")
        sp.add_argument("--platforms", help="Redes separadas por comas (por defecto, todas las activadas)")

    d = sub.add_parser("demo", help="Prototipo: video completo con recursos sintéticos y voz local")
    production_args(d)
    d.set_defaults(func=cmd_demo)
    r = sub.add_parser("render", help="Produce un video con clips locales y la biblioteca de música")
    production_args(r)
    r.add_argument("--clips", default=str(PROJECT_ROOT / "assets" / "clips"), help="Carpeta con clips.json")
    r.add_argument("--music-library", help="Biblioteca de música alternativa")
    r.set_defaults(func=cmd_render)
    dy = sub.add_parser("day", help="Produce todos los guiones de una fecha (ambos idiomas, todas las redes)")
    dy.add_argument("--date", help="AAAA-MM-DD (por defecto, hoy)")
    dy.add_argument("--queue", default=str(PROJECT_ROOT / "data" / "scripts" / "queue"), help="Carpeta de guiones")
    dy.add_argument("--source", choices=["local", "pexels"], default="local")
    dy.add_argument("--clips", default=str(PROJECT_ROOT / "assets" / "clips"), help="Carpeta con clips.json")
    dy.add_argument("--music-library", help="Biblioteca de música alternativa")
    dy.add_argument("--demo-assets", action="store_true", help="Usa clips y música sintéticos de prueba")
    dy.add_argument("--platforms", help="Redes separadas por comas (por defecto, todas las activadas)")
    dy.add_argument("--force", action="store_true")
    dy.add_argument("--allow-similar", action="store_true")
    dy.set_defaults(func=cmd_day)
    ex = sub.add_parser("export", help="Rehace las carpetas por red a partir de un maestro existente")
    ex.add_argument("master", help="Carpeta output/<idioma>/_master/<tema>")
    ex.add_argument("--platforms", help="Redes separadas por comas")
    ex.set_defaults(func=cmd_export)
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
