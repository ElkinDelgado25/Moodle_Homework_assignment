# Auditoría general del proyecto

**Fecha:** 16 de noviembre de 2026
**Versión auditada:** 0.4.5 → 0.5.0
**Alcance:** dependencias, seguridad, ejecución, instalación, integración continua y rendimiento.
**Método:** lectura del código y de los flujos de instalación, resolución del entorno con `uv`, auditoría de vulnerabilidades, medición de arranques y ejecución completa de la suite.

## Resumen

- Se actualizaron todas las dependencias con versión estable disponible y se ajustaron los rangos para que `uv` no vuelva a resolver versiones antiguas.
- `pip-audit` no encuentra vulnerabilidades en las dependencias de ejecución fijadas en `uv.lock`.
- El CLI pasó de ~1,7 s a ~0,3 s en los comandos ligeros al importar cada comando solo cuando se usa.
- La instalación fija Python 3.13 y compila el bytecode, que es donde Windows y macOS pagaban más tiempo de arranque.
- El CI prueba Python 3.11 y 3.13, cachea Chromium y verifica la instalación real del wheel en Windows, Debian, Arch y macOS.
- Se incorporó Ruff como red de seguridad estática y se corrigieron todos sus hallazgos.
- Dependabot queda programado para revisar dependencias y acciones cada semana.

## 1. Dependencias

| Componente | Antes | Después | Motivo |
| --- | --- | --- | --- |
| Playwright | 1.63.0 | 1.65.2 | Versión estable más reciente; corrige fallos de automatización. |
| pydantic | 2.13.5 | 2.14.3 | Correcciones de validación y rendimiento. |
| pypdf | 6.21.4 | 7.1.0 | Nueva serie estable; se verificó la lectura de PDF en los entregables. |
| sentry-sdk | 2.72.0 | 2.75.0 | Correcciones del cliente de errores. |
| tomlkit | 0.15.1 | 0.15.2 | Corrección de escritura de configuración de agentes. |
| certifi | 2026.4.22 | 2026.10.23 | Corrige `PYSEC-2026-4320`. |
| opentelemetry-api | — | 1.45.2 | Dependencia de `mcp`; corrige `CVE-2026-126360`. |
| fpdf2 | 2.8 | 2.9 | Serie estable actual; sin cambios de API en el uso actual. |
| mcp | 2.x | 2.3 | API estable vigente del SDK. |
| Pillow | 10 | 13 | Serie estable actual, con límite `<14`. |
| Rich | 13.9 | 15 | Serie estable actual, con límite `<16`. |
| python-docx | 1.1 | 1.2 | Correcciones de generación de DOCX. |
| python-dotenv | 1.0.1 | 1.2 | Lectura de `.env` sin cambios de comportamiento. |

Los rangos quedaron con el siguiente mayor como límite (`>=X.Y,<X+1`) para que una resolución nueva no salte de serie sin revisión.

`requires-python` se mantiene en `>=3.11` por compatibilidad, pero la instalación recomendada usa 3.13. El CI comprueba ambos intérpretes para no romper esa promesa.

## 2. Seguridad

La auditoría se ejecuta sobre las dependencias de ejecución exportadas desde el lockfile, no sobre el intérprete global del equipo:

```bash
uv export -q --locked --no-dev --no-emit-project --no-hashes \
  --format requirements.txt --output-file requirements-audit.txt
uv run pip-audit -r requirements-audit.txt
```

Resultado: **no known vulnerabilities found** con `pip-audit 2.10.1`.

Durante la revisión aparecieron dos avisos que ya estaban corregidos por las versiones elegidas:

- `PYSEC-2026-4320` en `certifi`: resuelto con 2026.10.23.
- `CVE-2026-126360` en `opentelemetry-api`: resuelto con 1.45.2.

Nota práctica: si ejecutas `pip-audit` sin `-r`, audita el Python global y puede mostrar vulnerabilidades de paquetes que el proyecto no usa (LangChain, por ejemplo). Usa siempre el archivo exportado.

## 3. Ejecución y rendimiento

Medido en Windows 11, Intel de 12 hilos, SSD y Python 3.13.7:

| Escenario | Antes | Después |
| --- | --- | --- |
| `mcp-moodle --help` (comando ligero) | ~1,7 s | 0,31–0,39 s |
| Importación del servidor MCP en caliente | ~1,3–1,8 s | igual (depende del equipo) |
| Primer arranque tras instalar | compilaba bytecode al usar | compila durante la instalación |

Cambios responsables:

1. **Imports perezosos en `cli.py`.** `status`, `tasks` y `update` ya no cargan `mcp`, Playwright ni los generadores de documentos. Una prueba de arquitectura impide que esos imports vuelvan al nivel superior.
2. **Python 3.13** mediante `moodle_tasks.PYTHON_VERSION`, usado por los instaladores, `mcp-moodle update` y el CI.
3. **`--compile-bytecode`** en `uv tool install`: el primer arranque no compila cientos de módulos.

El detalle por plataforma, las recomendaciones para Windows y el trabajo futuro (reutilizar Chromium entre llamadas) están en [RENDIMIENTO.md](../RENDIMIENTO.md).

## 4. Instalación y actualización

- `scripts/install.py` y `scripts/ci_verify_install.py` instalan con Python 3.13 y `--compile-bytecode`.
- `moodle_tasks/updates.py` aplica la misma versión y compilación al actualizar, de modo que `mcp-moodle update` no deja un entorno más lento que una instalación nueva.
- `docs/INSTALL.md` explica requisitos, qué hace el instalador, cómo actualizar y cómo desinstalar.
- Se mantiene la instalación desde un clon con Git como único método soportado.

## 5. Integración continua

`.github/workflows/tests.yml` ahora incluye:

- Tarea `unit` con matriz Python 3.11/3.13 que ejecuta la suite completa antes de empaquetar.
- Caché de Chromium con clave `playwright-<sistema>-<hash de uv.lock>` en las cinco plataformas.
- `setup-uv` 10.3.3 y `actions/cache` 6.1.0, fijadas por SHA.
- Cancelación de ejecuciones obsoletas de una misma pull request.
- Paso de Ruff en Ubuntu antes de construir el wheel.
- Verificación de instalación real (CLI, Chromium y servidor MCP) en Windows Server 2025, Ubuntu 24.04, Arch Linux y macOS 15 en Intel y Apple Silicon.

## 6. Calidad estática

Se añadió Ruff 0.17.5 en el grupo `dev` con un conjunto acotado: `E4,E7,E9,F,B,UP,RUF100`. No se activó el orden de imports (`I`) para no reescribir el estilo de todo el repositorio en esta auditoría.

Hallazgos corregidos:

- `zip()` sin `strict` en el renderizador PDF.
- `datetime.timezone.utc` sustituido por `datetime.UTC`.
- Variables de bucle no usadas y una lambda asignada a un nombre.
- Imports y `noqa` obsoletos.
- En las pruebas, los manejadores de Playwright capturaban mal las variables del bucle: un parámetro extra hacía que Playwright pasara el objeto `Request` como estado. Ahora se enlazan con una fábrica de manejadores.

## 7. Mantenimiento

`.github/dependabot.yml` revisa cada lunes:

- Dependencias Python del proyecto (`uv`), agrupando parches y menores en una sola pull request.
- Acciones de GitHub, agrupadas.

Las actualizaciones mayores se ignoran a propósito: pueden exigir cambios de API y deben revisarse a mano.

## 8. Hallazgos pendientes

| Tema | Estado | Recomendación |
| --- | --- | --- |
| Reutilizar Chromium entre llamadas MCP | No implementado | Playwright sincrónico ata los objetos al hilo; requiere un hilo dedicado con cola. Ahorraría 0,5–1,5 s por llamada. |
| Orden de imports (`I` en Ruff) | No activado | Aplicarlo en un cambio aparte para no mezclarlo con correcciones funcionales. |
| Cobertura de pruebas | Sin medir | Añadir `coverage` al CI y fijar un umbral gradual. |
| Exclusiones de Defender en Windows | Documentado, no automatizado | No se toca la configuración de seguridad del equipo del usuario. |
| Dependencias de desarrollo | Solo Ruff | `pip-audit` no se instala como dependencia del proyecto; se ejecuta cuando se audita. |

## 9. Verificación

```bash
uv run python -m unittest discover -s tests -v
uv run ruff check src tests scripts
```

- 329 pruebas correctas, 8 omitidas por requerir red o un Moodle real.
- Ruff sin hallazgos.
- `pip-audit` sin vulnerabilidades sobre el lockfile de ejecución.
- Instalación del wheel verificada en CI en las cinco plataformas.

## 10. Cómo reproducir esta auditoría

1. `uv sync --locked --python 3.13`
2. `uv run python -m unittest discover -s tests -v`
3. `uv run ruff check src tests scripts`
4. Exportar requisitos y pasar `pip-audit` como se indica en la sección 2.
5. Medir arranques con varias repeticiones y quedarse con la mediana; comparar siempre el mismo equipo y la misma versión de Python.

## Anexo: commits de la auditoría

| Commit | Cambio |
| --- | --- |
| `edadc65` | Dependencias a versiones estables y límites de serie. |
| `ac4bc23` | Imports perezosos en el CLI y prueba de arquitectura. |
| `845bfaf` | Python 3.13 y bytecode en instalación, actualización y CI. |
| `b830d8d` | Matriz 3.11/3.13, caché de Chromium y acciones actualizadas. |
| `8760f35` | Ruff, correcciones estáticas y arreglo de los manejadores de Playwright. |
| `1cf5127` | Dependabot semanal para `uv` y acciones. |
| `f93afcb` | Guía de rendimiento. |
| `7051dd8` | Requisitos, actualización y desinstalación en la guía de instalación. |
