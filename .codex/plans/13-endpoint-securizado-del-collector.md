# Plan de la issue #13: feat: securizar endpoint de disparo del collector

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/13
- **Repositorio de seguimiento:** `aldeapucela/biki-stats-core`
- **Repositorio de implementación:** `aldeapucela/biki-stats-core`
- **Estado:** IMPLEMENTACIÓN AUTORIZADA
- **Rama futura:** `feat/13/endpoint-securizado-del-collector` (todavía no creada)
- **Base de rama:** `main`

## Resumen verificable de la issue

La captura programada actual se ejecuta en `.github/workflows/collector.yml` sobre un runner autoalojado con las etiquetas `self-hosted, movilidad`. Si ese runner no está conectado, GitHub Actions no puede garantizar que se importen nuevos datos.

La issue solicita un endpoint interno de la API que permita a GitHub Actions pedir una captura GBFS al servidor desplegado, con autenticación explícita, reutilización del pipeline existente y comprobaciones que impidan ejecuciones no autorizadas o concurrentes.

## Alcance confirmado y exclusiones

### Incluido

- Endpoint `POST /api/v1/ops/collector/run`.
- Autenticación mediante `Authorization: Bearer <token>`.
- Configuración del token mediante `MOVILIDAD_COLLECTOR_TOKEN`.
- Reutilización de `CapturePipeline`, proveedor GBFS, repositorio SQLite y locks existentes.
- Respuestas diferenciadas para petición válida, token ausente/inválido, captura en curso y fallo de captura.
- Actualización del workflow programado para invocar el endpoint por HTTPS con `curl`.
- Uso de un secreto de GitHub Actions llamado `MOVILIDAD_COLLECTOR_TOKEN`.
- Documentación de configuración, despliegue, comprobación y requisitos de HTTPS/reverse proxy.
- Tests unitarios y de API para autenticación, ejecución y errores.

### Excluido

- Autenticación de usuarios de la API pública.
- Panel de administración o gestión de tokens desde la aplicación.
- Persistencia de tokens en SQLite.
- Token en query string, logs, respuestas JSON o mensajes de error.
- Cambios en los contratos públicos de estaciones e histórico de la issue #4.
- Sustitución del collector CLI como herramienta local.

## Contexto y dependencias

- La API se publica externamente como `https://api.aldeapucela.org/biki/`.
- La web se publica como `https://biki.aldeapucela.org`.
- El reverse proxy debe terminar HTTPS y reenviar el prefijo `/biki/` según la configuración del despliegue.
- La API y el collector deben compartir `/data/movilidad.sqlite3`.
- El pipeline existente ya registra capturas, libera locks en éxito/error y evita duplicados por proveedor.
- GitHub Actions necesita el secreto `MOVILIDAD_COLLECTOR_TOKEN` y una URL de API configurable o documentada.
- La implementación debe partir de `main` en una rama `feat/13/endpoint-securizado-del-collector`.
- Las modificaciones locales no relacionadas que estén pendientes en `README.md` y `docker-compose.yml` se conservarán y no se sobrescribirán.

## Propuesta técnica (NO EJECUTAR)

1. **Configuración y dependencia de autenticación**

   - Añadir `collector_token` a `Settings`, con alias `MOVILIDAD_COLLECTOR_TOKEN`.
   - No proporcionar un token por defecto en producción.
   - Crear una dependencia FastAPI específica que extraiga el esquema Bearer, compare el valor mediante `secrets.compare_digest` y devuelva `401` sin revelar si falta o es incorrecto.
   - No incluir el endpoint en el contrato público de lectura; se puede ocultar de OpenAPI si la decisión pendiente sobre operación interna lo confirma.

2. **Caso de uso de captura**

   - Extraer o reutilizar un servicio de aplicación que construya la conexión, repositorio, proveedor GBFS y `CapturePipeline` a partir de `Settings`.
   - Ejecutar una captura síncrona dentro de la petición para que GitHub Actions conozca el resultado real.
   - Traducir la captura concurrente a `409 Conflict` y los errores del proveedor/persistencia a una respuesta `5xx` segura.
   - Cerrar siempre la conexión SQLite en un bloque `finally`.
   - Mantener el lock SQLite como protección principal frente a llamadas simultáneas desde workflow, cron o CLI.

3. **Router y respuestas**

   - Añadir un router operativo bajo `/api/v1/ops`.
   - Definir schemas Pydantic mínimos para respuesta de captura, sin incluir secretos.
   - Devolver un identificador de captura y el resultado agregado cuando la captura finalice correctamente.
   - Mantener el formato de errores y request ID existente.

4. **Workflow de GitHub Actions**

   - Sustituir el job que requiere `self-hosted, movilidad` por una ejecución en runner hospedado que llame por HTTPS al endpoint.
   - Usar `curl --fail-with-body --silent --show-error`, método `POST`, cabecera Bearer y timeout explícito.
   - Guardar la URL base como variable de entorno y el token únicamente como secreto.
   - Hacer que cualquier respuesta HTTP no exitosa marque el job como fallido.
   - Mantener `workflow_dispatch` para ejecutar una captura manual.
   - Conservar la concurrencia del workflow para evitar solicitudes superpuestas.

5. **Documentación y despliegue**

   - Documentar `MOVILIDAD_COLLECTOR_TOKEN` en `.env.example` sin valor real.
   - Documentar el secreto equivalente de GitHub Actions, la URL del endpoint y una prueba `curl` segura sin mostrar el token.
   - Documentar que el endpoint solo debe publicarse detrás de HTTPS y que el proxy debe enrutar `/biki/api/v1/ops/collector/run`.
   - Actualizar la documentación del despliegue para preferir la captura remota y mantener el collector local como alternativa operativa.

## Dudas y decisiones (resolver TODAS antes de codificar)

| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| ¿La petición espera al resultado de la captura? | Síncrona con resultado real; asíncrona con `202` y seguimiento posterior | Síncrona para que GitHub Actions detecte el fallo de importación en el mismo job | Resuelta |
| ¿El endpoint aparece en OpenAPI? | Ocultarlo por ser operativo interno; mostrarlo documentado | Ocultarlo y documentarlo en la guía de despliegue | Resuelta |
| ¿Qué variable contiene la URL llamada por Actions? | Fija en workflow; variable de repositorio; secreto/variable de entorno | Variable `COLLECTOR_API_URL` en el workflow, sin incluir credenciales | Resuelta |
| ¿Qué hacer si no se configura token? | Fallar al arrancar; devolver `503` al endpoint; desactivar endpoint | La API arranca y el endpoint responde `503` | Resuelta |
| ¿Debe mantenerse el collector autoalojado? | Sustituirlo por HTTP; mantener ambos como fallback; retirar solo después | Sustituir el job por HTTP y mantener el comando/cron local como fallback | Resuelta |
| ¿Debe limitarse el endpoint por IP además del token? | Solo Bearer sobre HTTPS; allowlist de IP; mTLS | Solo Bearer sobre HTTPS | Resuelta |
| ¿Qué contrato devuelve la captura? | Mínimo; detalle completo; siempre `202` | `200` con `capture_id`, `409` ocupada, `401` auth y `5xx` error | Resuelta |

## Pruebas y validación propuestas

- Tests de configuración cuando el token está presente y ausente.
- Tests de dependencia: Bearer válido, ausente, mal formado e incorrecto.
- Test que verifica que el token nunca aparece en el cuerpo de error ni en logs capturados.
- Test del endpoint con un proveedor GBFS falso: inicia el pipeline, devuelve el `capture_id` y persiste la captura.
- Test de captura concurrente que devuelve `409` y no crea una segunda corrida.
- Test de error del proveedor que libera el lock y devuelve un error controlado.
- Test del workflow/configuración de Compose y validación completa mediante `scripts/validate.sh`.
- Prueba manual local con `curl` y token temporal.
- Prueba en servidor mediante `workflow_dispatch`, verificando nueva observación, logs y healthcheck.

## Riesgos y criterios de aceptación

### Riesgos

- Un endpoint expuesto sin HTTPS permitiría robar el token.
- Una ejecución síncrona puede ocupar un worker durante la llamada al proveedor; el timeout debe estar alineado con el workflow y el número de workers desplegados.
- Si API y collector no comparten volumen, la captura puede completarse en otra SQLite y no ser visible para la API.
- El tag del secreto no debe aparecer en logs de `curl`, GitHub Actions ni respuestas.
- El workflow puede ejecutarse con retraso; el lock existente debe hacer la operación segura e idempotente.

### Criterios de aceptación

- Una llamada sin token o con token inválido responde `401` y no ejecuta el collector.
- Una llamada válida sobre HTTPS ejecuta el mismo pipeline que el collector local.
- Una captura concurrente responde `409` sin corromper ni duplicar datos.
- Los errores de GBFS o SQLite producen un fallo observable en GitHub Actions y dejan el lock liberado.
- El workflow programado cada cinco minutos funciona desde un runner hospedado sin depender del runner `movilidad`.
- El token solo existe en la configuración del servidor y en el secreto de GitHub Actions; nunca en el repositorio.
- La documentación permite configurar la URL, el token, el volumen y verificar una captura.
- La validación existente continúa pasando sin romper la API pública.

## Autorización expresa para empezar a escribir código

- [x] Todas las dudas resueltas.
- [x] Recibida autorización explícita para **implementar esta issue**.
- **Referencia o texto de autorización:** «Adelante» / «Implement the plan» (2026-10-20).

**Mientras falte cualquiera de las condiciones anteriores, solo editar este documento.**
