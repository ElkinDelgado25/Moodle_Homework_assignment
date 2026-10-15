# Entregables de tareas

Cuando el usuario pide «hagamos la primera», «resuelve esta tarea» o continuar una actividad elegida, el agente consulta `get_assignment` y sigue su campo `assignment_workflow` hasta producir los entregables. La respuesta incluye `assignment_id`, las instrucciones de Moodle y sus enlaces, y `document_template` con la portada y el formato. No hace falta pedir por separado que consulte el MCP, use la plantilla o genere el PDF. Si el usuario solo solicita información, esta consulta no inicia la creación de archivos.

Antes de redactar, el agente descarga y lee los anexos de esa misma actividad e identifica los requisitos, rúbrica y evidencias solicitadas. El contenido debe resolver esos requisitos: un resumen genérico, un TXT con una URL o una operación de Git no completan el trabajo. Si se exige una aplicación, código u otro producto, también debe prepararlo según la consigna y documentar el trabajo real, sin inventar capturas ni resultados. Los formatos explícitos de la consigna y del usuario tienen prioridad sobre los predeterminados.

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

`get_assignment` incluye esos mismos datos en `document_template`, por lo que no requiere otra llamada para obtenerlos. Si el perfil local es inválido, conserva las instrucciones de la actividad y devuelve `document_template=null` con el motivo en `document_template_error`. El agente puede avanzar en el contenido y debe resolver ese error antes de usar la plantilla. Los datos faltantes de portada no impiden preparar el desarrollo; solo debe preguntar por información necesaria que no esté disponible.

## Formato APA 7

El desarrollo usa Times New Roman de 12 puntos, papel carta, márgenes de 2,54 cm, interlineado doble, alineación izquierda, sangría inicial de 1,27 cm y cero espacio adicional entre párrafos. Los encabezados de primer nivel van centrados y en negrita; los de segundo nivel, a la izquierda y en negrita. Se numeran todas las páginas desde la portada, arriba a la derecha, sin encabezado abreviado ni bordes de página.

En las entregas de prácticas con repositorio se omiten las citas autor-fecha y la sección de referencias bibliográficas, salvo petición explícita de la consigna o del usuario. El formato APA de página y tipografía no obliga a añadir bibliografía. Un tutorial usado como consigna no se convierte automáticamente en una referencia del informe.

Cuando el trabajo requiera bibliografía, las citas usan autor y fecha. Las referencias verificadas se ordenan alfabéticamente, con interlineado doble y sangría francesa de 1,27 cm. Cada fuente citada debe corresponder a una referencia y viceversa. No se inventan autores, fechas, enlaces ni fuentes. Las tablas llevan número, título en cursiva y notas cuando corresponda; se evitan líneas verticales y cuadrículas decorativas. El interior de tablas puede usar interlineado sencillo para mejorar la legibilidad.

## Enlace del repositorio en prácticas

El agente consulta los remotos Git del proyecto trabajado y confirma en GitHub el propietario, nombre y URL web canónica, mediante la página del repositorio o la API (por ejemplo, `gh repo view --json url,nameWithOwner`). No construye enlaces a partir del nombre de la carpeta ni reutiliza repositorios de otras tareas. Si hay varios remotos, distingue el proyecto del estudiante del repositorio original del tutorial. Una consulta `git fetch` no verifica el hipervínculo del documento ni demuestra que el trabajo local esté publicado.

En DOCX y PDF, el texto visible y el destino del hipervínculo deben ser exactamente la URL web confirmada, conservando guiones, guiones bajos y demás caracteres. No se insertan espacios, saltos manuales, puntuación ni caracteres invisibles dentro del enlace. Después de exportar, el agente comprueba también el destino del enlace en ambos archivos y que el repositorio corresponde a la práctica; la revisión visual por sí sola no comprueba el destino.

Si no puede confirmar la URL o necesita acceso, comunica la limitación y solicita el enlace exacto cuando sea necesario. Un 404 sin autenticar no demuestra que el repositorio no exista. Las incidencias de Git o de preparación se informan en la conversación y se incluyen en el documento únicamente si la consigna lo requiere.

La portada conserva el logo y los bloques institucionales que pidió el usuario. Es una adaptación institucional y no la portada estudiantil estándar de APA. La base de formato se apoya en la [guía de APA para trabajos estudiantiles](https://www.apa.org/ed/precollege/psn/2020/09/apa-style-student-papers).

El perfil opcional `document_profile.json` se guarda junto a `credentials.env` en la configuración personal. Es un objeto JSON con los campos anteriores y valores de texto. El servidor solo devuelve esos campos; rechaza perfiles mal formados. Los nombres personales no se incorporan a la plantilla pública del paquete.

Los nombres, docentes, materias y semestres concretos pertenecen al perfil local o al documento de cada tarea; no se versionan en la plantilla. Git excluye `document_profile.json`, sus variantes `document_profile.*.json` y las carpetas locales `output/` y `private/`. Si se usa el perfil, sus datos deben confirmarse para la tarea actual: una materia o un semestre anterior no se trasladan automáticamente a otra tarea. La plantilla del paquete conserva únicamente los marcadores editables.

La plantilla y el logo están incluidos en `src/moodle_tasks/assets/`. Para reconstruir la plantilla en desarrollo, ejecuta `scripts/build_document_template.py` en un entorno con `python-docx`. Esta dependencia no se necesita para consultar la plantilla por MCP.

## Alcance

El MCP proporciona la plantilla y las instrucciones de entrega. El agente del cliente crea el contenido y convierte los archivos con sus herramientas de documentos; esta herramienta no genera respuestas académicas ni convierte archivos por sí sola. Las instrucciones guían al cliente, pero no garantizan que todos los modelos las cumplan. Antes de entregar, el agente debe contrastar el contenido con cada requisito de la consigna, renderizar y revisar todas las páginas del DOCX y el PDF. Si falta material esencial o falla la conversión, comunica el bloqueo o el archivo faltante y no declara terminada la tarea.

Después de presentar los enlaces locales del DOCX y PDF, el agente pregunta si el usuario quiere subir ambos archivos a la misma tarea de Moodle, salvo que ya lo hubiera pedido. Una petición explícita o un «sí» autoriza `upload_assignment_files`. La herramienta comprueba que los archivos existan, que la tarea acepte entregas y que no haya otros archivos ya adjuntos. Si Moodle ya muestra archivos, no los reemplaza; el usuario debe pedir el reemplazo expresamente. La subida guarda los archivos en la entrega, pero no los envía para calificación. El agente comunica los archivos confirmados y cualquier error parcial.

Después de actualizar el paquete, reinicia el MCP en el cliente para que descubra `get_document_template()` y cargue las instrucciones nuevas.
