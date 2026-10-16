# Investigación: métricas no disponibles de `/portfolio_status`

Fecha: 2026-10-16 (UTC)

## 1. Resumen ejecutivo

Se inspeccionó el código del repositorio `ccantero/django_render` en el commit `82e32fd04d525e5e13dd098fd3194d3f4968e33c` mediante la integración de GitHub. El checkout local de este workspace no contiene el repositorio (`git rev-parse` falla), por lo que no fue posible ejecutar sus pruebas ni verificar una rama distinta de la revisión consultada.

El motivo inmediato de que los horizontes 7d/30d se representen como `unavailable` es claro en el código: no basta con una serie reciente ni con snapshots de otra fuente. El lector necesita un snapshot más reciente que seis horas y un snapshot `bot_cycle` con `notes.portfolio_equity_usdt` positivo y válido dentro de 6–8 días (7d) o 28–32 días (30d). Si no encuentra uno, asigna `None`; el formatter lo muestra como `unavailable`. El mensaje observado por sí solo no identifica cuál condición falló.

En los archivos inspeccionados no hay evidencia PostgreSQL actual ni una regla de retención de `portfolio_snapshots` confirmada. Por lo tanto, no se puede confirmar la causa de producción ni atribuirla a una retención. La ausencia de una línea base canónica dentro de la ventana es la causa lógica inmediata; el porqué de esa ausencia permanece sin verificar.

Los drivers de 24h están intencionalmente sin implementar en el lector Django: el summary fija `equity_drivers_24h` en `None`. El formato imprime `unavailable`. Aunque existen `drivers_24h` internos de realized/unrealized y una guía de atribución futura en el contrato del bot, no equivalen a atribución histórica del cambio total de equity.

La gráfica es una serie visual de siete días, generada desde las mismas filas leídas, pero filtrada/agrupada separadamente; no muestra etiquetas de eje con fechas ni valores. No debe interpretarse como gráfica de 24h/30d ni como la misma serie exacta usada para los cambios textuales.

No se modificó código, base de datos, configuración, rama ni PR. No se ejecutaron pruebas porque el código no está en el workspace.

## 2. Revisiones y alcance

- Repositorio principal: `ccantero/django_render`, revisión consultada `82e32fd04d525e5e13dd098fd3194d3f4968e33c`.
- Repositorio relacionado: documentación `ccantero/binanceBot`, consultada en su rama predeterminada cuando se pudo; no se pudo asociar aquí un SHA verificable de esa revisión. El documento local adjunto `project_sources/11-DATA_CONTRACT.md` es copia de contrato versionada `1.0.62`, verificada el 2026-09-26; no se asume que represente el HEAD actual del bot.
- `AGENTS.md` remoto: establece modo `INVESTIGATION` para análisis sin cambios; este trabajo se mantuvo en ese alcance.
- Revisados: `README.md`, `docs/DATA_CONTRACT.md`, `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, `docs/KPI_REGISTRY.md`, `docs/PROJECT_STATE.md`, `PLAN.md`, `docs/CHANGELOG.md`, `core/views.py`, `core/telegram_diagnostics.py`, `dashboard/services/telegram_portfolio_status.py` y `core/tests.py`.
- La documentación local adjunta del proyecto se leyó desde `project_sources/`; no se leyó ni se accedió a los adjuntos mediante Library.
- No se encontró localmente `AGENTS.md`, `README.md`, `manage.py`, ni `.git`; fueron inspeccionados de forma remota los archivos rastreados encontrados por búsqueda GitHub. No se pudo leer `dashboard/tests.py` en la ruta asumida porque devolvió 404; la cobertura pertinente aparece en `core/tests.py`.

## 3. Mapa de implementación

Referencias de línea para la revisión `82e32fd…`:

1. **Registro/dispatch.** `core/telegram_diagnostics.py:43-60` incluye `/portfolio_status` en `DIAGNOSTIC_COMMANDS`; `diagnostic_response` despacha a `format_portfolio_status()` (`:86-106`). `core/views.py:144-202` recibe el webhook, importa el dispatcher de forma diferida y entrega foto/texto; `/help` lo anuncia.
2. **Lectura de balance y estado actual.** `core/telegram_diagnostics.py:408-430` lee el healthcheck más reciente y toma `free_usdt` solo si no supera `HEALTHCHECK_STALE_MINUTES` (default de settings); `:432-449` consulta lotes abiertos (`remaining_quantity > 0`) y precios de `Portfolio` para esos símbolos.
3. **Snapshots.** `:_bounded_portfolio_snapshot_rows` (`:377-405`) selecciona `source="bot_cycle"`, `created_at` entre `now-35d` y `now`, orden descendente por `created_at,id`, limitado a `PORTFOLIO_STATUS_MAX_SNAPSHOTS` (default 512), luego invierte a orden cronológico. Settings configura dicho valor en `django_render/settings.py:53`. No incluye `notes` en el filtro SQL.
4. **Histórico.** `PortfolioEquityHistoryBuilder` en `dashboard/services/telegram_portfolio_status.py:208-…` valida fuente, timestamp, equity positivo, frescura y tolerancias. Usa `created_at` como timestamp del punto y `notes.portfolio_equity_usdt` como valor (`:504-509`).
5. **Cálculo actual y summary.** `build_portfolio_status` (`dashboard/services/telegram_portfolio_status.py:27-124`) calcula open value y equity usando lotes abiertos, proyección `portfolio.current_price` y `free_usdt` reciente. Devuelve cambios históricos, puntos de gráfica y métricas actuales. `equity_drivers_24h` queda explícitamente `None` (`:113-120`).
6. **Texto.** `render_portfolio_status` (`:127-…`) imprime 24h/7d/30d y agrega `unavailable` para drivers falsy (`:140-160`).
7. **PNG y entrega.** `PortfolioEquityChartRenderer.render_png` genera bytes PNG in-memory (`dashboard/services/telegram_portfolio_status.py`, desde la clase del renderer); `format_portfolio_status` intenta generarlo solo si hay al menos dos puntos visuales y deja fallback textual si falla (`core/telegram_diagnostics.py:467-475` y siguientes). El webhook envía la imagen como foto cuando existe y texto en fallback (tests `core/tests.py:6572-6660`).
8. **Configuración dependiente del entorno.** `PORTFOLIO_STATUS_MAX_SNAPSHOTS` default 512; `HEALTHCHECK_STALE_MINUTES` alimenta tanto frescura de free USDT como `stale_after` de precio actual. El histórico usa su propio `max_latest_age=6h`; no es el umbral de healthcheck.

Los números de línea anteriores son del commit remoto indicado, no de un checkout local.

## 4. 7 días

- Horizon nominal: 7 días.
- Límite aceptado por el código: edad entre 6 y 8 días, inclusiva (`WINDOW_TOLERANCES`; builder `_point_for_window`). Entre candidatos selecciona el más cercano a 7 días; empate favorece el timestamp más antiguo.
- El último snapshot canónico usable debe tener edad no negativa y no mayor que 6h. El builder rechaza el conjunto si el último usable es más viejo.
- Todo snapshot debe tener `source="bot_cycle"`, `created_at <= as_of`, y `notes.portfolio_equity_usdt` numérico, finito y `>0`. No usa `portfolio_sync_from_api`, `open_value_usdt`, la columna `portfolio`, balances actuales ni lotes para reconstruir la historia.
- El lector SQL toma hasta 512 filas más recientes de los últimos 35 días. Si existen más de 512, una línea base de 6–8 días puede quedar fuera por límite aunque exista en la base; los tests comprueban selección limitada, no cardinalidad real en producción.
- Sin candidato en 6–8 días: `changes["7d"] = None`; el formatter lo representa como `unavailable`. No interpola.
- Evidencia documental: `project_sources/14-DJANGO_DESIGN.md:290-309`; contrato local `project_sources/11-DATA_CONTRACT.md:1302-1317`; implementación remota arriba.
- **Conclusión de producción:** no establecida. Requiere inspección read-only de snapshots actuales y conocer el límite efectivo/retención.

## 5. 30 días

Las mismas reglas de validez y de snapshot más reciente aplican. La diferencia es la ventana histórica: 28–32 días. El query de Django pide como máximo 35 días, de modo que el horizonte cae dentro del lookback solicitado, pero no garantiza que quede dentro de las 512 filas más nuevas.

Si no hay candidato válido en 28–32 días, `changes["30d"] = None`. La documentación del contrato exige persistir los snapshots requeridos; no establece en el pasaje consultado una política de retención de snapshots. Una retención que eliminara filas de más de siete días explicaría la falta de datos, pero aquí es solo hipótesis y debe contrastarse con el bot/DB actuales. No confundir con la retención de siete días documentada para `sell_decision_events`, que es otra tabla.

## 6. Drivers de equity 24h

- En el código, `equity_drivers_24h` se asigna a `None` de forma incondicional en el summary. La salida observada está, por diseño actual, desconectada de una atribución histórica computada.
- El summary también conserva una clave `drivers_24h` con un driver de realized derivado de cierres del día UTC y un `unrealized` basado en contribuyentes unrealized **actuales** y el signo del cambio 24h. Esa compatibilidad interna no se usa como el campo de atribución renderizado; el registry clasifica los antiguos drivers como deprecated y dice que no se muestran.
- La documentación de datos del bot describe `notes.symbols` como evidencia opcional de valoración por símbolo en cada snapshot, con `quantity`, `current_price`, `value_usdt`, solo para comparación de dos snapshots canónicos. El contrato local también dice que no se debe fabricar para filas históricas. El lector Django inspeccionado no consulta ese campo para construir `equity_drivers_24h`.
- Para atribución defensible faltaría verificar que ambos snapshots tengan `symbols` completos y comparables, tratar apariciones/desapariciones, posiciones vendidas/compradas entre snapshots, activos sin precio, fees y componentes cash. Aun con `symbols`, el cambio del valor abierto por símbolo no explica necesariamente todo el cambio de equity.
- `equity(t1)-equity(t0)` incluye variación de free USDT más open value. Depósitos/retiros, transferencias, compras/ventas, fees e ingresos/salidas pueden cambiar caja/equity sin equivaler a trading PnL. `Realized PnL` visible es calendario UTC de hoy, no ventana móvil de 24h; unrealized es fotografía actual. Ninguno debe presentarse como explicación del cambio total.
- La documentación propone el rótulo prudente `Open-position contribution`, no `Explained`. Incluso si se implementa, el remanente debe distinguirse como no atribuido/limitado, no forzarse a sumas balanceadas.

## 7. Gráfica: ventana, consulta y escala

- **Ventana real:** últimos siete días desde `as_of` (código `CHART_WINDOW=7d`), no un período inferido del tamaño de la imagen. Las filas se toman del mismo resultado de la query de 35 días, pero luego se filtran a `chart_start <= timestamp <= as_of`.
- **Fuente:** exclusivamente filas `bot_cycle` con `notes.portfolio_equity_usdt` finito/positivo. Usa `created_at`.
- **Límite de consulta:** hasta 512 snapshots por defecto, configurable. Si el volumen de 35 días supera el límite, la selección previa al builder puede reducir la representación temporal disponible.
- **Reducción visual:** por defecto se limita a 96 puntos, conservando el último punto de cada bucket temporal; luego se rechazan puntos que superen 25% de variación absoluta respecto al último punto visual aceptado. Esto afecta solo la gráfica, no cambios textuales. Menos de dos puntos tras filtro => gráfica no disponible.
- **Ejes:** renderer dibuja “EQUITY HISTORY”, ejes y líneas guía, pero no dibuja ticks, valores USDT ni fechas. Normaliza X entre timestamp mínimo/máximo presente y Y entre equity mínima/máxima presente. Por ello no permite leer el valor absoluto ni la fecha de cada punto; cambios pequeños pueden parecer grandes por autoescala.
- **Spikes:** pueden reflejar variación real de equity, caja, cambios de posiciones, fees, fuente/captura incompleta o error de datos. El gráfico filtra saltos grandes, pero no los valida como falsos; el texto puede conservar cambios calculados con puntos que la imagen excluyó. Sin snapshots actuales, no se clasifica ningún spike observado como error.
- **Consistencia:** los textos 24h/7d/30d usan puntos canónicos validados antes del filtro visual; chart usa subconjunto de 7d después de downsample/outlier filter. Comparten fuente de lectura inicial, no exactamente la misma serie final ni ventana para 30d.

## 8. Hechos confirmados e hipótesis

### Hechos confirmados por código/documentación

- Hay ruta y handler para `/portfolio_status`; pruebas enfocadas existen en `core/tests.py`.
- El histórico no sustituye datos faltantes por cero ni reconstruye equity desde el estado actual.
- 7d/30d requieren baselines dentro de tolerancias específicas y un latest snapshot de no más de 6h.
- El query está acotado a 35 días y 512 filas por defecto.
- `equity_drivers_24h` es `None` en el builder actual; la sección muestra `unavailable`.
- La gráfica representa siete días, puede bajar a 96 puntos y visualmente omite saltos >25%; no dibuja etiquetas de ejes.
- El contrato del bot documenta `notes.symbols` opcional y límites de atribución.

### Hipótesis que requieren evidencia actual

- La tabla no tiene ningún snapshot canónico válido dentro de la ventana requerida.
- Snapshots existentes fueron excluidos por fuente, timestamp, valor JSON ausente/inválido/no positivo o por el corte de 512 filas.
- Una retención o cambio de productor bot explica ausencia de snapshots antiguos; no hay regla de retención de snapshots probada en los documentos leídos.
- Un spike proviene de una captura inválida, movimiento de caja o cambio real de cartera.

## 9. Base de datos, entorno y reproducibilidad

No se encontraron credenciales ni variables `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` o `PGPASSWORD` en el entorno; `psql` tampoco estaba disponible. No se verificó si existe PostgreSQL local ni se intentó conexión alguna. Por seguridad no se intentó descubrir ni conectar a producción. La copia de `DATA_CONTRACT.md` no es evidencia de filas de base.

Para obtener evidencia actual, el operador puede ejecutar estas consultas manualmente en una sesión `psql` conectada conscientemente a una réplica/sandbox autorizada o a producción con rol read-only. Confirme la conexión antes de ejecutar. No incluir credenciales en el informe. Espera el esquema `bot` y columnas documentadas `id, source, created_at, notes`; el tipo de `notes` debe confirmarse en el catálogo antes de usar operadores JSON. Las consultas solo leen y tienen ventanas/límites explícitos.

```sql
BEGIN READ ONLY;
SET LOCAL statement_timeout = '5s';

-- Q1. Muestra la ventana cubierta por las 512 filas más recientes dentro de 35d,
-- número de filas devueltas y fechas de extremos. No demuestra cuáles notes son válidas.
WITH recent AS (
  SELECT id, source, created_at, notes
  FROM bot.portfolio_snapshots
  WHERE source = 'bot_cycle'
    AND created_at >= now() - interval '35 days'
    AND created_at <= now()
  ORDER BY created_at DESC, id DESC
  LIMIT 512
)
SELECT count(*) AS rows_returned,
       min(created_at) AS oldest_selected,
       max(created_at) AS newest_selected,
       count(*) FILTER (WHERE notes ? 'portfolio_equity_usdt') AS key_present
FROM recent;

-- Q2. Enumera solo hasta 512 filas seleccionadas y sus ventanas de edad.
-- La conversión defensiva exige JSON numérico o string decimal compatible.
WITH recent AS (
  SELECT id, source, created_at, notes
  FROM bot.portfolio_snapshots
  WHERE source = 'bot_cycle'
    AND created_at >= now() - interval '35 days'
    AND created_at <= now()
  ORDER BY created_at DESC, id DESC
  LIMIT 512
), parsed AS (
  SELECT id, created_at,
         CASE
           WHEN jsonb_typeof(notes::jsonb -> 'portfolio_equity_usdt') IN ('number','string')
            AND (notes::jsonb ->> 'portfolio_equity_usdt') ~ '^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$'
           THEN (notes::jsonb ->> 'portfolio_equity_usdt')::numeric
         END AS equity
  FROM recent
)
SELECT id, created_at, now() - created_at AS age,
       equity,
       CASE
         WHEN created_at >= now() - interval '6 hours' THEN 'latest_candidate'
         WHEN created_at BETWEEN now() - interval '8 days' AND now() - interval '6 days' THEN '7d_candidate'
         WHEN created_at BETWEEN now() - interval '32 days' AND now() - interval '28 days' THEN '30d_candidate'
       END AS candidate_window
FROM parsed
WHERE equity > 0
  AND (created_at >= now() - interval '6 hours'
       OR created_at BETWEEN now() - interval '8 days' AND now() - interval '6 days'
       OR created_at BETWEEN now() - interval '32 days' AND now() - interval '28 days')
ORDER BY created_at DESC, id DESC;

-- Q3. Conteos básicos de fuente dentro de 35d; puede visitar más filas y no
-- determina integridad del JSON. Ejecutar solo si Q1/Q2 son rápidas y el timeout
-- es apropiado para el entorno.
SELECT source, count(*)
FROM bot.portfolio_snapshots
WHERE created_at >= now() - interval '35 days'
  AND created_at <= now()
GROUP BY source
ORDER BY source;

ROLLBACK;
```

Q1/Q2 describen lo que el Django lector puede seleccionar si settings conserva 512. Para diagnosticar truncamiento hace falta comparar `oldest_selected` con la ventana objetivo y confirmar si había candidatos más antiguos descartados; no asumir que el query planner tiene índice. Q3 puede escanear más datos; se propone solo como opcional con `statement_timeout`. Si `notes` es `json`/`jsonb`, el cast y `?` aplican; si su tipo difiere, ajustar tras consulta de catálogo read-only. Una ausencia en estos resultados apoya la hipótesis para esa conexión y hora, no demuestra por sí sola por qué la fila no existe o fue purgada.

## 10. Pruebas ejecutadas y pendientes

No se ejecutaron tests: no hay checkout ni `manage.py` local; `pytest`/dependencias no se verificaron mediante instalación. La respuesta de búsqueda GitHub contiene historial textual de tests, pero no se toma como ejecución presente. Tests pertinentes existentes se identificaron en `core/tests.py:5616-6559`, incluyendo selecciones acotadas, ventanas, fuente, valor canónico, frescura, límites de gráfica/outliers, texto y PNG. Ver plan independiente en `PORTFOLIO_STATUS_TEST_PLAN.md`.

## 11. Evaluación de causa y próximos pasos

- **7d:** código demuestra únicamente que falta un snapshot elegido en 6–8 días o que una condición previa de frescura/selección inutilizó el conjunto. Debe comprobarse en DB.
- **30d:** código demuestra el mismo requisito para 28–32 días. Falta investigar producción de snapshots y retención efectiva. No usar la retención de otras tablas como explicación.
- **Drivers:** no es una falla intermitente de datos: actualmente el campo renderizado no está implementado y se fija `None`. Atribución requiere una decisión contractual y evidencia histórica suficiente; actual unrealized y realized diario no la sustituyen.
- **Siguiente verificación autorizada por el alcance actual:** ejecutar Q1/Q2/Q3 de forma read-only en el entorno elegido, registrar fecha/instancia/versión sin secretos y conservar resultados mínimos. Revisar bot HEAD y job de snapshots/retención para 30 días. Después de revisión independiente, decidir si autorizar una implementación Django-only o si falta primero persistencia bot-owned.

No se implementó ninguno de estos pasos.
