---
name: github-issue-plan-first
description: "Aplicar cuando se solicita planificar, iniciar o implementar una issue de Movilidad enlazada desde GitHub. Consultar la issue central de biki-stats-core, intentar activar Plan mode, documentar el plan en .codex/plans/ del repositorio de implementación y esperar a resolver todas las dudas y recibir autorización explícita antes de escribir código."
---

# Movilidad · GitHub issue → plan → permiso → código

## Alcance y activación

Todas las issues de Movilidad (API, frontend, datos, infraestructura y documentación) se gestionan en https://github.com/aldeapucela/biki-stats-core/issues. El código se modifica en `biki-stats-core` o `biki-stats-web` según el alcance. **La ubicación de la issue no determina dónde debe implementarse.**

Activar esta skill al pedir **planificar, empezar o implementar** una issue, incluso si la URL de una issue es todo el encargo. **Si solo se pide crear, analizar, trasladar o clasificar issues, no crear un plan ni empezar código.**

## Fase A: planificación obligatoria (sin código)

1. Leer la **issue real** en GitHub: título, descripción, criterios de aceptación, comentarios, referencias y dependencias. Si no se puede consultar, detenerse; no inventar información.
2. Intentar activar **Plan mode**, si el entorno dispone de él. La skill no puede activarlo por sí sola. Si no está disponible, indicarlo y continuar exclusivamente con análisis, sin afirmar que se ha activado.
3. Identificar el **repositorio de implementación** y revisar su estado actual, arquitectura y documentación sin cambios destructivos. La rama base del proyecto es `main`.
4. Crear o actualizar **únicamente** `.codex/plans/{issueId}-{titulo-de-la-issue}.md`, usando `assets/plan-template.md`. Generar slug en minúsculas, sin tildes ni caracteres especiales, y sin guiones repetidos. Usar siempre el ID y la URL de la issue centralizada.
5. Separar requisitos confirmados, hipótesis, exclusiones, riesgos, dependencias, pruebas y preguntas con posibles soluciones.
6. Resolver **todas las dudas** con el solicitante y reflejar las decisiones adoptadas en el plan.
7. **Detenerse antes de implementar.** La mera URL, un «ok» ambiguo, el silencio o la aprobación del plan no autorizan a codificar. Preguntar explícitamente: «¿Puedo empezar a escribir código para la issue #N?».

### Bloqueo obligatorio

Hasta resolver todas las dudas y recibir permiso **explícito y específico para escribir código**, no crear/editar código, tests, scripts, migraciones, dependencias, configuración, ramas, commits ni PR. **La única modificación permitida durante la planificación es el documento de plan de esa issue.**

## Fase B: solo después de autorización explícita

1. Confirmar que todas las dudas están resueltas y registrar en el plan la autorización inequívoca para esta issue. Si surgen dudas relevantes nuevas, detenerse y actualizar el plan.
2. Verificar la existencia de `main`, comprobar que no se sobrescribe trabajo ajeno y crear desde esa rama:

   ```text
   {feat|fix}/{issueId}/{titulo}
   ```

   Ejemplo: `feat/2/diseno-responsive-frontend` en `biki-stats-web` para la issue central #2.
3. Implementar el alcance aprobado, documentar decisiones, añadir pruebas y validar los resultados.
4. Cada commit debe seguir exactamente:

   ```text
   {feat|fix}: {título}
   {descripción}
   Refs: {issueUrl}
   ```

5. Abrir PR hacia `main` del repositorio de implementación, enlazando issue y plan. No fusionar sin autorización.

## Consideraciones

- Categorías de rama/commit admitidas: `feat` y `fix`. No inventar una alternativa sin consultarlo.
- Código bajo AGPL-3.0-only; CC-BY-SA-4.0 solo para contenido original o datos legalmente licenciables. Verificar condiciones de los feeds GBFS e históricos externos.
- No exponer credenciales, datos personales ni material de terceros sin autorización.
- Seguir `AGENTS.md` y `docs/GUIA_DESARROLLO.md` del repositorio de implementación.
