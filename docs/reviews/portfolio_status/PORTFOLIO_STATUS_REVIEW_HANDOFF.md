# Handoff para revisión independiente

Fecha: 2026-10-16. Idioma de informes: español.

## Revisión y repositorios

- Repo Django: `ccantero/django_render`
- Commit examinado vía GitHub: `82e32fd04d525e5e13dd098fd3194d3f4968e33c`
- Repo bot relacionado: `ccantero/binanceBot`; se consultó `docs/DATA_CONTRACT.md` en rama predeterminada, pero no se fijó un SHA verificable en este entorno.
- El workspace local no es checkout Git: `git status --short --branch`, `git rev-parse --show-toplevel` y `git rev-parse HEAD` terminaron con `fatal: not a git repository`.
- No se encontró `AGENTS.md` en el workspace; remoto de Django leído y aplicado en modo `INVESTIGATION`.

## Archivos consultados

Código Django: `core/urls.py`, `core/views.py`, `core/telegram_diagnostics.py`, `dashboard/services/telegram_portfolio_status.py`, `core/tests.py`, `django_render/settings.py`.

Docs remotos Django: `README.md`, `PLAN.md`, `docs/DATA_CONTRACT.md`, `docs/DESIGN.md`, `docs/ARCHITECTURE.md`, `docs/KPI_REGISTRY.md`, `docs/PROJECT_STATE.md`, `docs/CHANGELOG.md`.

Docs adjuntos revisados desde scratch: `project_sources/01-FORENSIC_VM_RUNBOOK.md`, `02-DJANGO_KPI_REGISTRY.md`, `03-DJANGO_ARCHITECTURE.md`, `04-ANALYSIS.md`, `05-BUY_FLOW.md`, `06-STRATEGY_DECISIONS.md`, `07-SELL_FLOW.md`, `08-ACCOUNTING_REPAIR_RUNBOOK.md`, `09-PLAN.md`, `10-README.md`, `11-DATA_CONTRACT.md`, `12-ARCHITECTURE.md`, `13-DJANGO_CHANGELOG.md`, `14-DJANGO_DESIGN.md`, `15-DJANGO_README.md`, `16-DJANGO_PROJECT_STATE.md`, `17-DJANGO_PLAN.md`, `18-DESIGN.md`, `19-PROJECT_STATE.md`, `20-CHANGELOG.md`, `21-KPI_REGISTRY.md`.

## Hallazgos principales

- Historial necesita canonical `bot_cycle` y positivo `notes.portfolio_equity_usdt`; last usable <=6h, baseline 7d 6–8d y 30d 28–32d. Fuente: `dashboard/services/telegram_portfolio_status.py` (builder) y contrato `docs/DESIGN.md`; líneas exactas referidas en `PORTFOLIO_STATUS_INVESTIGATION.md`.
- Query en Django limita a 512 filas de 35 días por default. Truncamiento de baseline es posible con volumen alto; requiere DB evidence.
- `equity_drivers_24h` se setea explícitamente a `None`; la sección no está conectada a una atribución verificada. `notes.symbols` es evidencia bot opcional documentada, pero no se consume en el lector actual.
- PNG es 7d, máximo visual 96 puntos, outliers >25% excluidos solo visualmente. Renderer no dibuja ticks/valores/fechas; la autoescala dificulta lectura. La serie del chart no es la usada íntegramente en cambios de texto.
- No hay PostgreSQL actual ni evidencia de producción. No se debe llamar confirmado el root cause más allá de la condición de código.
- No se verificó una política de retención de `portfolio_snapshots`; no confundir con tablas que tengan 7 días de hot retention.

## Comandos ejecutados y resultados

- `pwd && rg --files ...` — mostró solo `project_sources/*`; sin repo, `manage.py` ni archivos de app locales.
- `rg --files -g '!.*'` — enlistó 21 documentos adjuntos.
- `git status --short --branch && git rev-parse ...` — falló porque el directorio no es repo Git.
- `command -v psql`, `command -v pytest` — sin salida; no disponibles en PATH.
- Python imprimió solo nombres de env vars relevantes de DB; resultado `[]` (ninguna presente). No imprimió credenciales.
- Búsquedas/fetch GitHub read-only al commit indicado; `dashboard/tests.py` en ruta supuesta devolvió 404. No se ejecutó `pytest`, Django checks, SQL ni prueba PostgreSQL.
- No se hizo conexión DB ni intento a producción.

## Afirmaciones no verificadas

- Que producción carezca de filas basales en ventanas 7d/30d.
- Que retención o un cambio de productor explique el estado.
- Que los snapshots seleccionados correspondan exactamente a los valores actuales observados por Telegram.
- Que cualquier spike real del gráfico sea error o movimiento real; falta evidencia de datos.
- Que el contrato bot adjunto local refleje el HEAD actual de `binanceBot`.

## Riesgos y supuestos

- `notes` se asume con representación JSON/JSONB según modelos/contrato; verificar tipo físico antes de query.
- Query Q1/Q2 supone límite efectivo 512. Confirmar settings desplegado.
- `created_at` es el timestamp usado por Django; no se confirmó si equivale al instante económico de observación.
- El payload de ejemplo en la propuesta es sintético y no es fixture ni snapshot observado.
- No se propone inferir PnL desde equity changes ni recuperar/backfill histórico.

## Decisiones que requieren aprobación

- Semántica del endpoint actual: snapshot contra snapshot o equity actual contra snapshot histórico.
- Tolerancias, frescura y reglas de cálculo para contrato versionado.
- Persistencia/retención bot-owned suficiente para baseline 30d y atribución histórica.
- Grado de cobertura requerido para atribución `notes.symbols` y tratamiento de flujos de cash/fees.
- Wording inicial Telegram y futura política auth/API/PWA.

## Artefactos

- `PORTFOLIO_STATUS_INVESTIGATION.md`
- `PORTFOLIO_METRICS_CONTRACT_PROPOSAL.md`
- `PORTFOLIO_STATUS_TEST_PLAN.md`
- `PORTFOLIO_STATUS_REVIEW_HANDOFF.md`

**Modificaciones:** ningún código fuente, base de datos, configuración, contrato canónico, rama o PR fue modificado. Los únicos archivos nuevos son los cuatro informes solicitados. No se creó migración, API, PWA, formatter ni backfill.
