# Entregables de tareas

Al resolver una tarea documental, el agente debe entregar exactamente dos archivos finales con el mismo nombre base:

- `.docx`, editable en Word o LibreOffice.
- `.pdf`, exportado desde ese DOCX para mantener la misma portada y contenido.

Ambos se guardan en la carpeta solicitada. HTML, ODT, Markdown, scripts y capturas de revisión se mantienen fuera de esa carpeta, como archivos temporales, salvo que el usuario pida otro formato. Los anexos descargados del docente son material de entrada y no cuentan como formatos de la solución.

## Portada

`get_document_template()` devuelve las rutas locales de la portada DOCX y su logo, los campos editables y los valores del perfil personal si existe. La plantilla incluye el logo ULEAM arriba a la izquierda en la primera página, numeración arriba a la derecha, Arial negro y bloques centrados con esta secuencia:

1. Universidad Laica “Eloy Alfaro de Manabí”.
2. Materia y nombre de la asignatura.
3. Docente y nombre confirmado.
4. Estudiantes y sus nombres.
5. Carrera.
6. Curso.
7. Año.

El agente copia la plantilla, reemplaza `{{subject}}`, `{{teacher}}`, `{{student_1}}`, `{{student_2}}`, `{{degree}}`, `{{class_group}}` y `{{year}}`, y adapta la cantidad de estudiantes cuando haga falta. Añade un salto de página después de la portada para comenzar el desarrollo. Los datos actuales de Moodle y las indicaciones del usuario tienen prioridad; no deben inventarse datos faltantes ni reutilizarse un docente de otra materia.

El perfil opcional `document_profile.json` se guarda junto a `credentials.env` en la configuración personal. Es un objeto JSON con los campos anteriores y valores de texto. El servidor solo devuelve esos campos; rechaza perfiles mal formados. Los nombres personales no se incorporan a la plantilla pública del paquete.

La plantilla y el logo están incluidos en `src/moodle_tasks/assets/`. Para reconstruir la plantilla en desarrollo, ejecuta `scripts/build_document_template.py` en un entorno con `python-docx`. Esta dependencia no se necesita para consultar la plantilla por MCP.

## Alcance

El MCP proporciona la plantilla y las instrucciones de entrega. El agente del cliente crea el contenido y convierte los archivos con sus herramientas de documentos; esta herramienta no genera respuestas académicas ni convierte archivos por sí sola. Antes de entregar, el agente debe renderizar y revisar todas las páginas del DOCX y el PDF.

Después de actualizar el paquete, reinicia el MCP en el cliente para que descubra `get_document_template()` y cargue las instrucciones nuevas.
