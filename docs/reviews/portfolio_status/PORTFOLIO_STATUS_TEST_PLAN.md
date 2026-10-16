# Plan de pruebas: `/portfolio_status` y contrato de métricas

Estado: plan, no implementación. Revisión examinada: `ccantero/django_render` `82e32fd04d525e5e13dd098fd3194d3f4968e33c`.

## 1. Cobertura existente identificada

`core/tests.py` contiene `TelegramPortfolioStatusTests` (aprox. líneas 5616–6559) y pruebas de transporte/webhook después de esa clase. La cobertura observada por nombres y contenido incluye:

- query acotada, orden cronológico, desempate por ID, límite configurable y fallback de límite inválido;
- uso de snapshot fresco al superar límite;
- texto con secciones performance y `unavailable`;
- tolerancias/horizontes, fuentes incompatibles, equity canónica ausente/invalidada, latest stale;
- disponibilidad de gráfica independiente de horizontes textuales;
- downsampling y filtros visuales de outliers; preservar cálculos textuales al filtrar gráfica;
- renderer PNG válido;
- ruta Telegram, fallback si envío de foto falla y no intentar imagen si no hay historia;
- fuentes actuales: saldo, lotes, precios, realized today y protección contra healthcheck stale;
- test de no escrituras en tablas del bot.

No se ejecutaron en esta investigación porque el repositorio no está clonado localmente.

## 2. Brechas

- La mayoría de cobertura del builder parece basada en objetos simples/mock; falta validar JSON real de PostgreSQL y QuerySet en el motor PostgreSQL.
- No se identifica test que pruebe la semántica de un `notes` no-objeto, clave decimal corrupta/NaN/Infinity, timestamp futuro, o timestamp de inserción distinto del tiempo efectivo de observación.
- Falta demostrar que el cap de 512 no omita una baseline objetivo en distribución real; testear escenario >512 donde el único baseline útil queda fuera.
- No está claro que Django y futuras respuestas API consuman el mismo objeto de servicio porque el servicio común aún no está propuesto/implementado.
- No hay semántica API versionada, machine-readable reasons, ni pruebas de status diferenciados.
- Atribución histórica no tiene pruebas de cálculo porque el campo siempre es `None`; sí hay test de ausencia.
- Gráfico y texto deliberadamente usan puntos visuales distintos; falta una prueba integrada que compruebe y documente ambos intervalos y endpoints.
- Performance contra cardinalidad PostgreSQL realista no se ha medido; índices y query plan no se verificaron.

## 3. Pruebas unitarias propuestas

### Selección histórica

1. Baseline válido en punto nominal de 24h/7d/30d produce monto y porcentaje exactos.
2. Probar ambos extremos inclusivos y puntos justo fuera de cada tolerancia.
3. Cuando hay varios candidatos, escoger el más cercano y desempatar con regla estable.
4. Missing latest, latest >6h, future timestamps, sólo fuentes no canónicas y sin snapshots producen status/reason correctos.
5. JSON `notes` ausente, lista, string malformado, null/empty, decimal corrupto, `NaN`, Infinity, 0 y negativo se rechazan como no válidos; ningún caso se convierte en cero.
6. `open_value_usdt` sin `portfolio_equity_usdt` no es fallback.
7. Límite inválido/0/negativo cae en fallback configurado; configuración mayor/menor se respeta.
8. Dataset de >512 con baseline en ventana descartado produce `snapshot_limit_truncated` solo si el servicio puede establecerlo; si no, razón prudente `baseline_not_found` y telemetría de truncamiento separada.
9. Equal created_at ordering is deterministic by `id` across DB and builder.
10. Assert intervals are half-open query bounds (`<= now`) and tolerance ranges behave at timezone-aware UTC boundaries.

### Estado y representación

11. Verificar distinción: available 0, unavailable null, stale existente viejo, error de consulta/cálculo.
12. Verificar `reference.timestamp`, `as_of`, `freshness_seconds`, source y ventana, evitando mezclar reloj local/UTC.
13. Prueba de consistencia: formatter Telegram y serializador futuro consumen un mismo fixture/objeto de métricas y expresan mismo número/status; el formatter conserva salida legacy aprobada.
14. Chart/text: período de 7 días, ejes/valores seleccionados, downsampling conserva primer/último punto apropiado, outlier visual no altera amount/percent textual.
15. Atribución: ambos snapshots con símbolos completos; símbolo sin precio/valor, missing symbols, entradas/salidas nuevas/cerradas y cobertura parcial deben devolver razón/coverage; nunca igualar a realized PnL.
16. Acceso solo lectura: el servicio no invoca `.save()`, `.create()`, `update`, `delete`, ni actualiza tablas bot-owned; usar mocks/spies y pruebas de permisos DB.

## 4. Integración PostgreSQL

Usar una base desechable independiente, nunca `DATABASE_URL` o credenciales productivas. Aplicar fixtures vía `TransactionTestCase`/setup transaccional en `bot` o respetar modelos `managed=False` mediante SQL de setup en schema desechable. Casos:

- insertar snapshots canónicos y `portfolio_sync_from_api` en JSONB y comprobar fuente/notes real;
- snapshots ausentes, latest stale, baseline válidas en cada borde, tie timestamps/IDs;
- >512 dentro de 35d y baseline dentro/fuera del conjunto retornado;
- verificar ordenación/limit SQL, parámetros timezone-aware y QuerySet evaluation;
- ejecutar como rol read-only y confirmar que lectura pasa y escritura falla; no usar rol de producción;
- analizar `EXPLAIN (ANALYZE, BUFFERS)` con dataset sintético representativo para evaluar índices y límite; no extrapolarlo como performance prod.

Deben reportarse explícitamente motor PostgreSQL/versión. SQLite puede complementar tests unitarios, pero nunca presentarse como validación PostgreSQL.

## 5. Rendimiento y escala

- Fixture de prueba con tamaño realista y distribución temporal (p. ej. frecuencia bot observada), JSONB y fuente mixta.
- Controlar que la query histórica retorne a lo sumo el límite configurado y que el filtro temporal pueda usar índice si existe.
- Medir tiempo/filas/bytes leídos y número de queries; sin full-table scans accidentales ni una query por símbolo.
- Evaluar si el filtro JSON se ejecuta en Django en memoria tras 512 filas; considerar índices/consulta alternativa solo después de medir, sin schema changes en esta tarea.
- Prueba de comportamiento si filas candidatas superan el cap, además de exactitud bajo carga.

## 6. Riesgos de regresión

- Cambiar la base de comparación sin cambiar etiqueta puede alterar significado financiero.
- Aceptar fuentes o campos fallback puede fabricar equity histórica aparente.
- Confluir `0`, `null`, `stale` y `error` puede inducir decisiones operativas incorrectas.
- Reusar servicio desde API sin permisos explícitos expone estados financieros.
- La serie chart puede ocultar spikes visualmente y no representar el cálculo textual.
- Añadir retención/columnas o escribir `symbols` es cambio bot-owned, fuera de una implementación Django-only.
- Cost basis incompleta o fees non-USDT puede alterar realized/unrealized atribución.

## 7. Evidencia necesaria antes de autorizar implementación

1. Lectura PostgreSQL read-only de Q1/Q2 (incluidas en `PORTFOLIO_STATUS_INVESTIGATION.md`) en base y fecha identificadas.
2. Revisión del HEAD actual de ambos repos, `AGENTS.md`, job productor y cualquier job/archive de retención de `portfolio_snapshots`.
3. Confirmación de si se quiere exactitud snapshot-to-snapshot o live projection-to-snapshot.
4. Aprobación explícita de contrato/versionado, reasons, tolerancias, freshness y wording de atribución.
5. Checkout local del commit evaluado y resultados de test suite focal; después integración PostgreSQL desechable.
6. Decidir por separado cualquier cambio al productor bot/schema; no incluido ni autorizado por esta investigación.
