# Auditoría de credenciales — 8 de octubre de 2026

## Resultado

No se encontraron las credenciales reales de Moodle en los archivos versionados, los objetos de Git ni el paquete distribuible. No hizo falta eliminar credenciales de commits ni reescribir el historial.

Se encontró una copia local en `.env`, ignorada por Git, con permisos `0644`. Se restringió a `0600`. El archivo personal `credentials.env`, fuera del repositorio, ya tenía permisos `0600`.

## Alcance y comprobaciones

- Se actualizaron las referencias remotas con `git fetch --all --prune`. Las referencias disponibles eran `main`, `origin/main` y `origin/HEAD`.
- Se compararon en memoria los usuarios y contraseñas guardados en ambos archivos locales, sin imprimirlos. La búsqueda incluyó texto literal, escapes, codificación de URL y Base64; para el usuario incluyó también la parte anterior a `@`.
- La primera revisión cubrió 39 archivos locales propios, 18 miembros del wheel y 472 objetos Git, incluyendo objetos no alcanzables mediante `git cat-file --batch --batch-all-objects`. Solo coincidió el `.env` local ignorado.
- Gitleaks 8.30.1, obtenido del repositorio oficial `gitleaks/gitleaks`, revisó el historial de todas las referencias y el directorio de trabajo con redacción completa. Ambas revisiones terminaron sin hallazgos. El historial tenía 74 commits al iniciar la auditoría.
- Se revisaron siete configuraciones y respaldos locales de agentes contra las credenciales conocidas: ninguna coincidencia.
- Se revisó cómo se cargan y guardan las credenciales, su registro en los agentes, los mensajes de error y los ejemplos. Los valores de los tests y `.env.example` son datos ficticios.

## Correcciones

- `.gitignore` excluye variantes `.env.*`, `credentials.env`, `credentials.*.env` y los temporales `.moodle-*`, manteniendo `.env.example` publicable.
- La representación de `Config` oculta la contraseña.
- Los errores de la consulta por terminal, la configuración, el estado y el servidor MCP ocultan las credenciales conocidas, incluidas variantes escapadas en URL. Esto cubre también fallos inesperados al verificar una contraseña nueva, antes de guardarla.
- Se añadieron pruebas para esos casos de exposición en errores.

## Límites

La búsqueda exacta cubre las credenciales actualmente guardadas; Gitleaks complementa la búsqueda con reglas generales para secretos históricos desconocidos. Un resultado sin hallazgos no garantiza detectar cualquier secreto ofuscado. No se auditaron copias externas, forks, registros remotos ni todo el contenido de dependencias de terceros. El `.env` local permanece disponible para compatibilidad y no se publica.
