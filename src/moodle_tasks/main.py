"""mcp-moodle tasks: consulta de tareas en la terminal."""

import argparse
import sys
from datetime import datetime

from .console import configure_utf8_streams
from .core import Assignment, is_pending
from .config import Config, load_config
from .errors import redact_credentials
from .listing import pending_table
from .search import MODES, search_assignments
from .session import ensure_login, moodle_page


def collect_assignments(config: Config, *, mode: str = "all", limit: int | None = None,
                        only_pending: bool = False, stats: dict | None = None, progress=None) -> tuple[list[Assignment], list[str]]:
    with moodle_page(config) as (_, page):
        ensure_login(page, config)
        return search_assignments(page, config, mode=mode, limit=limit,
                                  only_pending=only_pending, stats=stats, progress=progress)


def print_tasks(tasks: list[Assignment], incomplete: bool = False, reviewed_count: int | None = None,
                timeline_empty: bool = False) -> None:
    pending = [task for task in tasks if is_pending(task)]
    if pending:
        print(pending_table(pending))
        return
    if not tasks and timeline_empty and not incomplete:
        # Una línea de tiempo vacía es una consulta completa: Moodle no muestra actividades próximas.
        print("\nNo hay tareas próximas en la línea de tiempo de Moodle.")
        return
    stamp = datetime.now().astimezone().strftime("%A, %d/%m/%Y %H:%M")
    print(f"\nConsulta de Moodle: {stamp}")
    reviewed_count = len(tasks) if reviewed_count is None else reviewed_count
    print(f"Tareas revisadas: {reviewed_count}")

    if not tasks:
        if reviewed_count and not incomplete:
            print("\nNo se encontraron tareas que cumplan esta búsqueda entre las actividades revisadas.")
        else:
            print("\n⚠️ No se pudieron revisar tareas. No se puede confirmar si tienes entregas pendientes.")
        return

    if incomplete:
        print("\n⚠️ La consulta quedó incompleta; no se pueden descartar tareas pendientes.")
    else:
        print("\n✅ No se encontraron tareas pendientes entre las actividades revisadas.")


def main(argv: list[str] | None = None) -> None:
    configure_utf8_streams()

    parser = argparse.ArgumentParser(description="Consulta tareas de Moodle.")
    parser.add_argument("--mode", choices=MODES, default="upcoming")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("El límite debe ser mayor que cero.")
    limit = args.limit if args.limit is not None else None if args.mode == "all" else 5
    config = None
    try:
        config = load_config()
        stats = {}
        tasks, errors = collect_assignments(config, mode=args.mode, limit=limit,
                                          only_pending=True, stats=stats)
        for error in errors:
            print(redact_credentials(error, (config.username, config.password)), file=sys.stderr)
        print_tasks(tasks, incomplete=bool(errors), reviewed_count=stats.get("candidates_checked"),
                    timeline_empty=stats.get("timeline_status") == "empty")
        print(f"Alcance: {stats.get('coverage', '')}")
    except Exception as error:
        secrets = (config.username, config.password) if config else ()
        print(f"\n❌ No fue posible consultar Moodle: {redact_credentials(error, secrets)}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
