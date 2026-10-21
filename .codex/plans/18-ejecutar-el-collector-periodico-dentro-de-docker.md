# Plan de la issue #18: ejecutar el collector periódico dentro de Docker

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/18
- **Repositorio de seguimiento e implementación:** `aldeapucela/biki-stats-core`
- **Estado:** AUTORIZADO PARA IMPLEMENTACIÓN; fusión pendiente de revisión
- **Rama futura:** `fix/18/collector-periodico-docker`
- **Base de rama:** `main` actualizado (e698615)

## Resumen verificable de la issue
Sustituir capturas programadas en GitHub por un servicio collector permanente en Compose.

## Alcance confirmado y exclusiones
CLI one-shot preservada; --loop captura inmediatamente y espera BIKI_CAPTURE_INTERVAL_SECONDS tras cada intento. Reutilizar locks SQLite. Retirar workflow y cron, actualizar docs. Sin acceso al servidor, nuevos endurecimientos, cambios de puerto o importador en collector.

## Contexto y dependencias
run_capture crea esquema y usa pipeline con locks y registro de fallos. API conserva importación histórica startup. Imagen y volumen compartidos; servicios independientes sin dependencia del health API. No hay herramienta para activar Plan mode; planificación previa en modo actual.

## Propuesta técnica
Bucle con threading.Event y handlers SIGTERM/SIGINT: solicitar parada, permitir terminar captura activa y despertar espera. Restaurar handlers al salir. Excepciones ordinarias registradas y reintentadas tras intervalo; one-shot conserva propagación. Solo API construye una imagen local explícita; collector la reutiliza con pull_policy never para evitar exportaciones simultáneas a la misma etiqueta. Collector sin puertos ni health HTTP. stop_grace_period 120s para varias peticiones con timeout por defecto 20s, sin garantizar cota total de red. No cambiar stale locks tras SIGKILL.

## Dudas y decisiones
| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| Programación | API / servicio separado | Segundo servicio independiente | Resuelta |
| Cadencia | fija / espera tras intento | Espera tras intento sin catch-up | Resuelta |
| Fusión | inmediata / revisión | Esperar revisión explícita en chat | Resuelta |

## Pruebas y validación propuestas
Captura inmediata, intervalo, recuperación, parada durante espera y captura, SIGINT/SIGTERM y one-shot. scripts/validate.sh completo, Compose normal y puerto personalizado, construcción y CI GitHub. Buscar referencias obsoletas globales.

## Riesgos y criterios de aceptación
Collector sin puertos comparte SQLite con API; sin GitHub Secrets ni histórico. SIGKILL o vencimiento de gracia pueden interrumpir captura; locks previos sin cambios. Ajustar gracia si aumentan timeouts. PR adjuntada y CI verde; servidor sin cambios.

## Autorización expresa para empezar a escribir código
- [x] Todas las dudas resueltas.
- [x] Autorización explícita para implementar esta issue.
- **Referencia:** encargo actual «Encárgate implementación completa repo local y GitHub ... Implementa collector permanente ... push PR ... espera mi revisión ... antes de merge». Incluye crear issue específica y plan sin confirmación redundante. No fusionar hasta recibir revisión.

## Resultados de implementación
CLI --loop y servicio independiente implementados. Pruebas automatizadas de recuperación, intervalo, SIGTERM/SIGINT durante captura/espera y one-shot. Validación local completa correcta; Compose puerto estándar y personalizado correcto. Prueba Docker con feed sintético: siete capturas correctas en SQLite, estación servida desde API y parada limpia confirmada. Primera prueba detectó colisión al exportar dos builds con misma etiqueta; corregida construyendo solo API. No se ha accedido al servidor. CI y revisión del solicitante pendientes antes de fusión.
