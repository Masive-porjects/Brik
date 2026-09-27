# Lineamientos de Git, Ramas y Flujo de Trabajo — WaveAI

Este documento establece las políticas obligatorias de control de versiones y entregables para el proyecto **WaveAI**.

---

## 1. Commits Continuos y Obligatorios
1. **Commit al Finalizar Cada Tarea**:
   - Cada vez que se culmine una tarea, corrección de bug, mejora de interfaz o solicitud del usuario, el asistente DEBE realizar inmediatamente el commit respectivo en git.
   - **Prohibido terminar un turno o respuesta dejando cambios locales sueltos o sin commitear**.
2. **Mensajes Convencionales Claros**:
   - Utilizar el estándar de Conventional Commits:
     - `feat(...)`: Nuevas funcionalidades o integraciones.
     - `fix(...)`: Corrección de errores y bugs.
     - `style(...)`: Ajustes puramente visuales, CSS o diseño.
     - `refactor(...)`: Reestructuración de código sin cambio de comportamiento.
     - `docs(...)`: Documentación y reportes de fases.

---

## 2. Estrategia de Ramas
1. **Ramas de Fase**:
   - Cada fase se trabaja en una rama dedicada basada en `dev`:
     - Ejemplo: `feat/fase-5-historial-drafts-masters`
2. **Protección de Ramas Principales**:
   - **`main` nunca se toca directamente**.
   - Prohibido hacer push directo a `dev` o `main`; toda integración definitiva se realiza mediante Pull Requests (PRs).

---

## 3. Reportes de Fases y Documentación Continua
1. **Actualización Viva y Obligatoria de Reportes**:
   - Cada entrega, sub-fase (ej. 5.5, 5.6), corrección de bugs, optimización de latencia o ajuste de interfaz DEBE registrarse inmediatamente en el reporte de la fase activa: `docs/evidence/reports/REPORT_FASE_X.md`.
   - **El asistente no debe esperar a que el usuario solicite la actualización del reporte**: debe mantener el documento al día con cada commit relevante.
   - El informe debe incluir: Resumen ejecutivo detallado, esquema de base de datos/Supabase, componentes desarrollados, validación de compilación (`bun run build`) y próximos pasos.

---

## 4. Preservación de Contexto y Gestión de Compactions
1. **Recuperación Proactiva de Contexto**:
   - Ante reinicios de sesión, pérdida de contexto o compactación de memoria, el agente DEBE leer prioritariamente:
     1. El reporte de la última fase en `docs/evidence/reports/REPORT_FASE_X.md`.
     2. Los lineamientos activos en `.agents/rules/`.
     3. El `git status` y el historial reciente de commits (`git log -n 5`).
   - Esto evita pedirle al usuario explicaciones sobre decisiones ya tomadas o bugs ya resueltos.
2. **Transición Limpia de Fases tras PR & Merge**:
   - Cuando el usuario confirme que se realizó el PR y Merge a `dev`:
     1. Actualizar y consolidar el reporte de la fase concluida.
     2. Hacer `git checkout dev` y `git pull origin dev` para sincronizar.
     3. Crear la nueva rama de trabajo para la siguiente fase: `git checkout -b feat/fase-X-<nombre>`.
     4. Comenzar la implementación de la nueva fase inmediatamente sobre esa rama.
