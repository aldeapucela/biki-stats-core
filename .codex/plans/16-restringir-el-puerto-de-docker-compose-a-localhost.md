# Plan de la issue #16: Restringir el puerto de Docker Compose a localhost

- **Issue:** https://github.com/aldeapucela/biki-stats-core/issues/16
- **Repositorio de seguimiento e implementación:** `aldeapucela/biki-stats-core`
- **Estado:** AUTORIZADO PARA IMPLEMENTAR
- **Rama:** `fix/16/puerto-docker-localhost`, desde `main`.

## Resumen y alcance confirmado

Compose publica el puerto en todas las interfaces. Restringirlo a `127.0.0.1`
para que el acceso público pase por Nginx y documentar este comportamiento.
Conservar el puerto configurable, SQLite persistente y la conectividad saliente.
El despliegue y los demás cambios de seguridad quedan fuera de esta issue.

## Contexto y propuesta técnica

Issue y comentarios consultados; no hay comentarios ni dudas pendientes.
El entorno no ofrece una herramienta para activar Plan mode; se ha completado
el análisis y este documento antes de modificar código o crear la rama.

Cambiar exclusivamente la publicación de `api` a
`127.0.0.1:${PORT:-8004}:${PORT:-8004}` y explicar en README que Nginx
accede por localhost. No modificar el volumen ni el puerto interno de Uvicorn.

## Dudas y decisiones

| Duda | Alternativas | Decisión aprobada | Estado |
| --- | --- | --- | --- |
| Interfaz de publicación | Todas / localhost | Solo 127.0.0.1 | Resuelta |
| Alcance | Puerto / despliegue completo | Puerto y documentación | Resuelta |

## Pruebas, riesgos y criterios de aceptación

- Ejecutar `docker compose config` con puerto predeterminado y personalizado.
- Verificar `host_ip=127.0.0.1`, puerto correcto y volumen persistente conservado.
- Revisar el diff y esperar la validación CI antes de fusionar la PR.
- El acceso directo desde otros hosts dejará de estar disponible por diseño.
- No se requieren pruebas unitarias para este cambio de configuración.

## Autorización expresa

- [x] Todas las dudas resueltas.
- [x] Autorización explícita para escribir código, crear PR y fusionar en main.
- Solicitud del usuario: «puedes corregir lo del puerto en el proyecto [...] Hazlo
  con un pull request explicando los motivos y mergeas el pull request en main».
