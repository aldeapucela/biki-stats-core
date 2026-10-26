# Plan de la issue #20: Mejorar rendimiento de consultas históricas de la API

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/20
- **Repositorio de seguimiento:** `aldeapucela/biki-stats-core`
- **Repositorio de implementación:** `aldeapucela/biki-stats-core`
- **Estado:** IMPLEMENTACIÓN AUTORIZADA
- **Rama futura:** `feat/20/mejorar-rendimiento-de-consultas-historicas-de-la-api` (todavía no creada)
- **Base de rama:** `main`

## Resumen verificable de la issue

Las consultas históricas de 7, 30 y 90 días presentan picos de latencia y alguna petición de 30 días agotó 20 segundos. El frontend solicita `/history` y `/summary` por separado para cada periodo. Ambos endpoints abren su propia conexión, leen el mismo intervalo y agregan datos en Python.

La conexión de API ejecuta `PRAGMA journal_mode=WAL` y `ensure_schema()` en cada petición. Producción ejecuta Alembic antes de arrancar, por lo que la inicialización defensiva no debe estar en el camino normal de lectura.

## Alcance confirmado y exclusiones

Incluido:

- Mover la inicialización de esquema y configuración WAL fuera de las peticiones HTTP.
- Añadir observabilidad de duración total, SQL y volumen de observaciones procesadas.
- Añadir `GET /api/v1/stations/{station_id}/analysis` para devolver histórico y resumen en una operación.
- Mantener `/history` y `/summary` para compatibilidad, compartiendo la lógica optimizada.
- Calcular agregaciones `hour` y `day` en SQLite y conservar el relleno de buckets vacíos y los resultados actuales.
- Añadir caché acotada de resultados idénticos con TTL de 30 segundos.
- Validar con pruebas funcionales, concurrencia representativa y `EXPLAIN QUERY PLAN`.

Excluido:

- Eliminar o deprecar las rutas públicas existentes.
- Crear una tabla materializada diaria; se deja como evolución posterior si SQLite sigue siendo insuficiente.
- Cambiar de SQLite a PostgreSQL o ampliar el número de workers de Uvicorn.
- Cambios en el frontend; se implementarán en `biki-stats-web#8` cuando exista el endpoint.

## Contexto y dependencias

- El contrato actual está definido por `HistoryData` y `SummaryData`; sus respuestas deben conservarse.
- El nuevo endpoint recibirá los mismos parámetros `from`, `to`, `granularity` y `provider_id` que histórico, con las mismas validaciones y errores.
- La respuesta será `Envelope[AnalysisData]`, donde `AnalysisData` contendrá `history: HistoryData` y `summary: SummaryData`.
- La ruta nueva no cambia la semántica de `raw`, `hour`, `day`, fechas UTC, observaciones ausentes ni `missing_buckets`.
- Se añade la migración `0003_history_covering_index`: el índice existente se mantiene y se incorpora un índice de cobertura para evitar lecturas de tabla durante las agregaciones históricas.
- La caché será por proceso, con máximo 256 entradas y TTL de 30 segundos; la caducidad limita la antigüedad aunque el proceso comparta SQLite con el collector.

## Propuesta técnica (NO EJECUTAR)

1. **Conexiones y ciclo de vida**
   - Separar la configuración inicial de base de datos de la apertura de conexiones.
   - Ejecutar una única inicialización al arrancar FastAPI; mantener la creación defensiva para desarrollo/tests y dejar producción respaldada por Alembic.
   - Mantener por conexión únicamente pragmas locales necesarios, sin cambiar WAL en cada lectura.
   - Reducir la espera por bloqueo a un límite acotado, manteniendo el error `503 SERVICE_UNAVAILABLE` ya existente cuando SQLite no está disponible.

2. **Servicio y repositorio histórico**
   - Incorporar una operación de análisis que valide la estación una vez y obtenga histórico/resumen sin repetir la lectura completa.
   - Para `raw`, conservar la lectura de observaciones necesarias para el contrato actual.
   - Para `hour` y `day`, agrupar en SQL por bucket y devolver solo las filas agregadas; completar en la capa de aplicación los buckets sin observaciones.
   - Calcular el resumen mediante agregados SQL y conservar medias, mínimos/máximos, instantes, composición, observaciones y `missing_buckets` actuales.
   - Compartir la implementación entre `/analysis`, `/history` y `/summary` para evitar divergencias.

3. **Contrato HTTP y caché**
   - Añadir el router/modelo para `/api/v1/stations/{station_id}/analysis` con el mismo envoltorio, ETag, `Cache-Control`, request ID y errores que el resto de la API.
   - Mantener las rutas existentes y sus modelos sin cambios incompatibles.
   - Aplicar una caché acotada de análisis idénticos antes de ejecutar SQLite; incluir en la clave estación, proveedor, intervalo y granularidad.

4. **Observabilidad y documentación**
   - Añadir duración de petición y, para histórico/análisis, duración de consulta, filas leídas/agregadas y estado de caché en logs estructurados.
   - Actualizar `docs/API_V1.md` con la ruta combinada y documentar que las rutas antiguas siguen disponibles.

## Dudas y decisiones (resolver TODAS antes de codificar)

| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| Compatibilidad de histórico/resumen | Añadir `/analysis`, sustituir rutas actuales o no añadir endpoint | Añadir `/analysis` y conservar `/history` y `/summary` | Resuelta por el solicitante |
| Estrategia de agregación | Solo Python, SQL, tabla diaria materializada | SQL para `hour`/`day` y caché; sin tabla diaria en esta fase | Resuelta por el solicitante |
| Objetivo de rendimiento | Sin timeout, P95 < 1 s, P95 < 500 ms | P95 inferior a 1 s en los cuatro periodos bajo carga representativa | Resuelta por el solicitante |
| Forma de la respuesta nueva | Duplicar campos planos o anidar los contratos existentes | `data.history` y `data.summary`, reutilizando `HistoryData` y `SummaryData` | Decisión técnica del plan |
| TTL y tamaño de caché | Sin caché, TTL configurable o límites fijos | TTL 30 s y máximo 256 entradas por proceso | Decisión técnica del plan |

## Pruebas y validación propuestas

- Probar el nuevo endpoint con `raw`, `hour` y `day`, intervalos válidos, estación inexistente, proveedor inválido y fechas inválidas.
- Comparar `data.history` y `data.summary` de `/analysis` con las respuestas actuales de `/history` y `/summary` usando datos de fixture, incluidos buckets vacíos y valores nulos.
- Verificar que las rutas existentes siguen devolviendo el contrato actual y que ETag/304 continúa funcionando.
- Probar que la inicialización de esquema/WAL no se ejecuta por petición y que las conexiones siguen funcionando en tests y desarrollo.
- Generar una base representativa de 90 días y comprobar el plan de consulta y el número de filas procesadas.
- Ejecutar una prueba concurrente sobre los cuatro periodos, incluyendo histórico y resumen simultáneos, y verificar P95 < 1 s sin timeouts.
- Ejecutar `scripts/validate.sh` y la suite completa de pytest.

## Riesgos y criterios de aceptación

Riesgos principales: cambiar accidentalmente la semántica de los buckets vacíos, alterar medias al pasar de Python a SQL, servir datos obsoletos más allá de 30 segundos o mantener contención durante una importación/captura.

Se acepta cuando:

- Las peticiones normales no crean tablas ni cambian WAL.
- `/analysis` evita la lectura duplicada y mantiene los resultados de las dos rutas actuales.
- La agregación SQL conserva resultados, zonas horarias y buckets vacíos.
- La caché está limitada y respeta TTL/ETag.
- No aparecen timeouts en la prueba concurrente representativa y el P95 de los cuatro periodos es inferior a 1 segundo.
- La documentación y las pruebas quedan actualizadas.

## Autorización expresa para empezar a escribir código

- [x] Todas las dudas resueltas.
- [x] Recibida autorización explícita para **implementar esta issue**.
- **Referencia o texto de autorización:** «Empieza a escribir código» (autorización del solicitante en esta conversación).

**Mientras falte cualquiera de las condiciones anteriores, solo editar este documento.**
