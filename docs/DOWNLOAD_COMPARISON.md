# Comparación de descarga de anexos — 8 de octubre de 2026

Se probó el anexo real `Taller Semana 6.pdf` de la tarea «Amenazas y vulnerabilidades comunes, enfocada en inyección SQL», en Moodle ULEAM, desde este equipo.

| Método | Mediana de descarga | Resultado |
| --- | --- | --- |
| curl sin sesión | 0,754 s (una prueba) | HTTP 200, pero HTML de acceso de 40.727 bytes; no era un PDF. |
| curl con sesión | 0,312 s (tres pruebas) | PDF válido de 303.717 bytes. |
| Playwright con sesión | 0,300 s (tres pruebas) | PDF válido de 303.717 bytes. |

Los tiempos individuales con sesión fueron 0,642 / 0,312 / 0,297 s para curl y 0,297 / 0,300 / 0,309 s para Playwright. Se alternó el orden entre ambos métodos. Los archivos autenticados coincidieron por SHA-256 y comenzaron con `%PDF-`.

Las mediciones de descarga excluyen el inicio de sesión, que tomó 17,066 s en esta ejecución, y la lectura de la actividad. No representan el tiempo completo de una llamada MCP. Tres muestras de un archivo pequeño no prueban una ventaja general de velocidad: la diferencia entre medianas fue de unos 12 ms y depende de la red y el estado del servidor.

Para comparar curl con autenticación se usaron las cookies de la misma sesión de Playwright, pasadas al proceso solo por entrada estándar; no se guardaron cookies ni credenciales en archivos o en argumentos de línea de comandos. Los archivos de prueba se guardaron en una carpeta temporal y se eliminaron al terminar.

Se eligió Playwright dentro del MCP porque ya inicia sesión, comparte las cookies con `page.context.request` y permite renovar el acceso sin programas externos. Curl con sesión también funciona, pero requiere obtener y transmitir esa sesión; usar curl por sí solo no resuelve la autenticación. La herramienta nueva valida el contenido antes de guardarlo y devuelve las rutas locales al agente.

Las pruebas automatizadas cubren cookies compartidas con un servidor local y Chromium reales, sesión vencida, HTML presentado como anexo, PDF inválido, conservación de archivos existentes, redirecciones y resultados parciales del MCP. Las 87 pruebas de la suite pasaron después del cambio.
