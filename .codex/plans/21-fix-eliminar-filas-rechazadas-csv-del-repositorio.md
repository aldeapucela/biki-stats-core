# Plan de la issue #21: fix: eliminar filas_rechazadas.csv del repositorio

- **Issue de este repositorio:** https://github.com/aldeapucela/biki-stats-core/issues/21
- **Repositorio de seguimiento:** `aldeapucela/biki-stats-core`
- **Repositorio de implementación:** `aldeapucela/biki-stats-core`
- **Estado:** IMPLEMENTACIÓN AUTORIZADA
- **Rama:** `fix/21/eliminar-filas-rechazadas-csv-del-repositorio`
- **Base de rama:** `main`

## Resumen verificable de la issue

- La issue está abierta, etiquetada como `bug`, asignada a `pabloguti` y no tiene comentarios.
- `filas_rechazadas.csv` existe en la raíz, está versionado y contiene 935 líneas (310194 bytes).
- El fichero se introdujo en el commit `2e36319` como salida de depuración de la importación histórica.
- Contiene filas procedentes de `serherval/flujosbiki`, cuya redistribución no está autorizada según `docs/PROCEDENCIA_DATOS.md`.
- La propuesta explícita de la issue es borrar el fichero y añadirlo a `.gitignore`.

## Alcance confirmado y exclusiones

Incluido:

- Eliminar `filas_rechazadas.csv` del árbol versionado.
- Añadir una regla de `.gitignore` para impedir que vuelva a incluirse ese artefacto de depuración.
- Verificar que el fichero deja de estar versionado y que la regla de exclusión coincide con el nombre esperado.

Excluido:

- Cambios en la lógica de importación histórica o en el formato de sus salidas.
- Eliminación o modificación de otros datos, documentos, migraciones o artefactos.
- Cambios en `docs/PROCEDENCIA_DATOS.md` o en la licencia de datos.
- Ramas, commits, PR y cualquier modificación distinta de este documento mientras no exista autorización expresa.

Ampliación autorizada durante la revisión de la PR:

- Estabilizar `tests/test_api_contracts.py`, cuya prueba de análisis histórico dependía de la hora real de ejecución y fallaba en la rama base fuera del minuto `:00`. La corrección fija la fecha del fixture y no cambia el comportamiento de producción.

## Contexto y dependencias

- El repositorio es `biki-stats-core`; la issue pertenece al repositorio correcto para backend y datos.
- `.gitignore` ya excluye entornos, cachés, bases SQLite, backups y secretos, pero no el CSV indicado.
- El árbol de trabajo ya contiene cambios no relacionados (`.codex/plans/8-...` y `docs/investigaciones/`); deben conservarse intactos.
- La rama actual no es `main`; tras la autorización, la rama de implementación deberá crearse desde `main` con el nombre indicado arriba.

## Propuesta técnica (NO EJECUTAR)

1. Partir de `main` y crear `fix/21/eliminar-filas-rechazadas-csv-del-repositorio`.
2. Añadir `filas_rechazadas.csv` como entrada explícita de `.gitignore`.
3. Eliminar el fichero del índice y del árbol de trabajo.
4. Revisar el diff para confirmar que únicamente afecta a `.gitignore` y al CSV objetivo.
5. Ejecutar comprobaciones ligeras: `git check-ignore -v filas_rechazadas.csv`, `git ls-files --error-unmatch filas_rechazadas.csv` esperando ausencia y `git diff --check`.

## Dudas y decisiones (resolver TODAS antes de codificar)

| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| ¿Qué patrón debe ignorarse? | Nombre exacto `filas_rechazadas.csv`; patrón global para cualquier CSV de rechazos; directorio de artefactos | Nombre exacto `filas_rechazadas.csv`, porque es el artefacto identificado por la issue y no se debe ocultar ningún otro CSV potencialmente relevante | Resuelta por la propuesta explícita de la issue |
| ¿Debe cambiarse la lógica que genera el fichero? | Mantenerla; modificarla; eliminar también sus salidas | Mantener la lógica fuera de alcance: la issue solo solicita retirar el artefacto versionado y prevenir su reaparición accidental | Resuelta por alcance |
| ¿Hay que modificar la documentación de procedencia? | No; ampliar documentación | No, porque ya documenta el origen y la necesidad de autorización; la issue no pide cambios documentales | Resuelta por alcance |

## Pruebas y validación propuestas

- Confirmar que `.gitignore` reconoce exactamente `filas_rechazadas.csv`.
- Confirmar que `git ls-files` ya no devuelve el fichero tras su eliminación.
- Ejecutar `git diff --check` y revisar que no aparecen cambios ajenos.
- No se prevé ejecutar la suite completa, porque el cambio no modifica código ni comportamiento de ejecución.

Resultado de esta implementación:

- `filas_rechazadas.csv` no existe y no está en el índice.
- `git check-ignore -v filas_rechazadas.csv` confirma la regla exacta de `.gitignore`.
- `git diff --check --cached` termina correctamente.
- El cambio de implementación afecta únicamente a `.gitignore` y a la eliminación del CSV; se conservaron los artefactos no relacionados ya presentes en el árbol.
- La prueba de contrato se ejecuta con una fecha fija para que sus buckets horarios sean deterministas.

## Riesgos y criterios de aceptación

Riesgos:

- El árbol de trabajo tiene cambios no relacionados; la implementación debe evitar incluirlos.
- La eliminación es necesaria para no seguir distribuyendo datos de terceros sin autorización; no debe conservarse una copia versionada en otra ruta.

Criterios de aceptación:

- `filas_rechazadas.csv` ya no está presente ni rastreado por Git.
- `.gitignore` contiene una regla exacta que evita volver a rastrear ese fichero.
- No hay cambios en lógica, documentación o ficheros no relacionados.

## Autorización expresa para empezar a escribir código

- [x] Todas las dudas resueltas.
- [x] Recibida autorización explícita para **implementar esta issue**.
- **Referencia o texto de autorización:** «Comienza a escribir el codigo» (usuario, 2026-10-26).

La implementación queda autorizada para esta issue; cualquier cambio de alcance requerirá nueva confirmación.
