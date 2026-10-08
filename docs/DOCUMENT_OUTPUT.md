# Entregables de tareas

Al resolver una tarea documental, el agente debe entregar exactamente dos archivos finales con el mismo nombre base:

- `.docx`, editable en Word o LibreOffice.
- `.pdf`, exportado desde ese DOCX para mantener la misma portada y contenido.

Ambos se guardan en la carpeta solicitada. HTML, ODT, Markdown, scripts y capturas de revisión se mantienen fuera de esa carpeta, como archivos temporales, salvo que el usuario pida otro formato. Los anexos descargados del docente son material de entrada y no cuentan como formatos de la solución.

## Portada

`get_document_template()` devuelve las rutas locales de la portada DOCX y su logo, los campos editables, el formato APA 7 y los valores del perfil personal si existe. La plantilla incluye el logo ULEAM arriba a la izquierda en la primera página, numeración arriba a la derecha, Times New Roman negro de 12 puntos y bloques centrados con esta secuencia:

1. Universidad Laica “Eloy Alfaro de Manabí”.
2. Materia y nombre de la asignatura.
3. Docente y nombre confirmado.
4. Estudiantes y sus nombres.
5. Carrera.
6. Curso.
7. Año.

El agente copia la plantilla, reemplaza `{{subject}}`, `{{teacher}}`, `{{student_1}}`, `{{student_2}}`, `{{degree}}`, `{{class_group}}` y `{{year}}`, y adapta la cantidad de estudiantes cuando haga falta. Añade un salto de página después de la portada para comenzar el desarrollo. Los datos actuales de Moodle y las indicaciones del usuario tienen prioridad; no deben inventarse datos faltantes ni reutilizarse un docente de otra materia.

## Formato APA 7

El desarrollo usa Times New Roman de 12 puntos, papel carta, márgenes de 2,54 cm, interlineado doble, alineación izquierda, sangría inicial de 1,27 cm y cero espacio adicional entre párrafos. Los encabezados de primer nivel van centrados y en negrita; los de segundo nivel, a la izquierda y en negrita. Se numeran todas las páginas desde la portada, arriba a la derecha, sin encabezado abreviado ni bordes de página.

Las citas usan autor y fecha. Las referencias verificadas se ordenan alfabéticamente, con interlineado doble y sangría francesa de 1,27 cm. Cada fuente citada debe corresponder a una referencia y viceversa. No se inventan autores, fechas, enlaces ni fuentes. Las tablas llevan número, título en cursiva y notas cuando corresponda; se evitan líneas verticales y cuadrículas decorativas. El interior de tablas puede usar interlineado sencillo para mejorar la legibilidad.

La portada conserva el logo y los bloques institucionales que pidió el usuario. Es una adaptación institucional y no la portada estudiantil estándar de APA. La base de formato se apoya en la [guía de APA para trabajos estudiantiles](https://www.apa.org/ed/precollege/psn/2020/09/apa-style-student-papers).

El perfil opcional `document_profile.json` se guarda junto a `credentials.env` en la configuración personal. Es un objeto JSON con los campos anteriores y valores de texto. El servidor solo devuelve esos campos; rechaza perfiles mal formados. Los nombres personales no se incorporan a la plantilla pública del paquete.

La plantilla y el logo están incluidos en `src/moodle_tasks/assets/`. Para reconstruir la plantilla en desarrollo, ejecuta `scripts/build_document_template.py` en un entorno con `python-docx`. Esta dependencia no se necesita para consultar la plantilla por MCP.

## Alcance

El MCP proporciona la plantilla y las instrucciones de entrega. El agente del cliente crea el contenido y convierte los archivos con sus herramientas de documentos; esta herramienta no genera respuestas académicas ni convierte archivos por sí sola. Antes de entregar, el agente debe renderizar y revisar todas las páginas del DOCX y el PDF.

Después de actualizar el paquete, reinicia el MCP en el cliente para que descubra `get_document_template()` y cargue las instrucciones nuevas.
