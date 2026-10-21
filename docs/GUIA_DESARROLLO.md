# Guía de desarrollo · BIKI

Esta guía aplica a **biki-stats-core** (Python/FastAPI/SQLite) y **biki-stats-web** (JavaScript vanilla/Tailwind). Buscamos que las personas voluntarias colaboren con claridad y previsibilidad.

## 1. Issues de cada repositorio

Las issues de backend/API/datos se crean en [biki-stats-core](https://github.com/aldeapucela/biki-stats-core/issues) y las de frontend/UI/analítica web en [biki-stats-web](https://github.com/aldeapucela/biki-stats-web/issues). Cada issue, rama, plan, commit y PR pertenecen al **mismo repositorio**. Para tareas transversales se crean issues independientes, enlazadas mediante URL completa.

**Crear una issue no autoriza a iniciar su planificación.** El desarrollador elaborará el plan cuando se le encomiende trabajar en ella.

## 2. Al empezar a trabajar en una issue

1. Leer la URL de la issue real en GitHub, con requisitos, comentarios y dependencias.
2. Intentar activar **Plan mode**; si no existe, permanecer en análisis e indicarlo.
3. Crear o editar **solo** `.codex/plans/{issueId}-{titulo-de-la-issue}.md` en el repositorio de implementación.
4. Exponer todas las preguntas y registrar las decisiones y las pruebas previstas.
5. Obtener autorización **explícita e inequívoca para escribir código** en esa issue. No confundir con la aceptación de un plan o un «ok» ambiguo.
6. Mientras no se cumplan esas condiciones, no crear código, pruebas, dependencias, configuraciones, ramas, commits ni PR.

Skill: [github-issue-plan-first](../.agents/skills/github-issue-plan-first/SKILL.md).

## 3. Ramas, commits y PRs

Crear cada rama **desde `main`**, nunca desde otra rama de desarrollo:

```text
{feat|fix}/{issueId}/{titulo}
```

`titulo` es un slug en minúsculas sin tildes ni caracteres especiales. Ejemplo de rama de backend: `feat/3/arquitectura-backend` en `biki-stats-core`, asociada a https://github.com/aldeapucela/biki-stats-core/issues/3.

Solo tras recibir permiso para implementar:

```bash
git fetch origin main
git switch main
git pull --ff-only origin main
git switch -c feat/3/arquitectura-backend
```

Cada mensaje de commit:

```text
{feat|fix}: {título}
{descripción}
Refs: {issueUrl}
```

Ejemplo:

```text
feat: definir estilos del mapa
Implementar los estilos de mapa aprobados y sus estados accesibles.
Refs: https://github.com/aldeapucela/biki-stats-core/issues/3
```

Las PR apuntan a `main` del propio repositorio y enlazan su issue y su plan. Las dependencias de otros repositorios se referencian con URL completa.

## 4. Documentación y licencias

- Documentar cómo arrancar, probar y desplegar cada funcionalidad cuando se implemente.
- Comentar **el porqué** de las decisiones no evidentes; priorizar accesibilidad y pruebas.
- Código bajo GNU Affero General Public License v3.0: **AGPL-3.0-only** (ver `LICENSE`).
- Datos originales licenciables: **CC BY-SA 4.0** solo con derechos suficientes (ver `DATA_LICENSE.md`).
- No relicenciar feeds de BIKI ni históricos externos sin verificar condiciones y atribución.
