# AGENTS.md · Movilidad (Aldea Pucela)

Este documento aplica a cualquier asistente que trabaje en este repositorio.

## Organización del trabajo

- **Repositorio central de issues:** https://github.com/aldeapucela/biki-stats-core/issues.
- **Repositorio de implementación:** se determina según cada issue. Una issue de frontend puede estar centralizada en `biki-stats-core` y desarrollarse en `biki-stats-web`.
- Al **planificar o implementar** una issue de GitHub, seguir obligatoriamente `.agents/skills/github-issue-plan-first/SKILL.md`.
- Si se solicita únicamente **crear, analizar, organizar o actualizar issues**, no generar planes de desarrollo ni escribir código.
- Para iniciar una tarea: leer la issue y sus comentarios, intentar activar modo Plan, y preparar el plan en `.codex/plans/{issueId}-{titulo-de-la-issue}.md` del repositorio de implementación.
- Antes de resolver **todas las dudas** y recibir autorización explícita para escribir código de esa issue, **solo se puede crear o editar su documento de plan**. No crear ramas, código, tests, scripts, configuraciones, commits o PR. La aprobación del plan no autoriza por sí sola la implementación.

## Convenciones

- Las ramas de trabajo salen **siempre de `main`** del repositorio de implementación: `{feat|fix}/{issueId}/{titulo}`.
- Commits con formato:

  ```text
  {feat|fix}: {título}
  {descripción}
  Refs: {issueUrl}
  ```

- `issueId` e `issueUrl` proceden del repositorio central `biki-stats-core`.
- Pull requests contra `main` del repositorio donde se desarrolla el código.
- Código: AGPL-3.0-only. Datos/obras originales autorizados: CC-BY-SA-4.0. No atribuir automáticamente esta última licencia a datos de terceros.
- Documentar en español para facilitar la incorporación de voluntarios y nunca publicar secretos.

Guía ampliada: [docs/GUIA_DESARROLLO.md](docs/GUIA_DESARROLLO.md).
