# Propuesta: contrato reutilizable de métricas de portfolio

Estado: diseño para revisión; no implementado. Versión propuesta inicial: `portfolio.metrics.v1`.

## 1. Límites arquitectónicos

| Capa | Propietario | Responsabilidad | No debe hacer |
|---|---|---|---|
| Datos canónicos | Binance Bot | Producir snapshots/evidencia bot-owned con provenance, tiempo, equity y, cuando sea válido, valor por símbolo | Django no debe escribir ni reinterpretar esas tablas como accounting |
| Cálculo de métricas | Django `dashboard.services.portfolio_metrics` (propuesto) | Lectura read-only, validación, ventanas, disponibilidad, cálculos y series estructuradas | Llamar a Binance, ejecutar trading o mutar contabilidad |
| Serialización HTTP | Django view/serializer (futuro) | Convertir el mismo resultado a JSON, autenticar, aplicar permisos/CSRF/caching apropiados | Recalcular fórmulas en serializer o duplicarlas por cliente |
| Presentación | Adaptadores Telegram, templates y PWA | Etiquetas, compactación, locale/formato y gráficos | Cambiar semántica o convertir `unavailable` en cero |

El contrato es una respuesta de servicio versionada y tipada conceptualmente; no exige una API HTTP inmediata.

## 2. Responsabilidades del servicio

Propuesta `PortfolioMetricsService.get_metrics(as_of, windows, history_limit)`:

- Seleccionar una sola vista de datos con orden determinista y límites explícitos.
- Calcular equity actual como proyección vigente definida y etiquetada, diferenciándola de snapshot histórico.
- Calcular horizontes con boundary, tolerancia y reference timestamp explícitos.
- Adjuntar freshness/provenance por métrica y por serie.
- Propagar estados de insuficiencia sin sustituir por cero.
- Calcular atribución solo si la evidencia de ambos extremos pasa validaciones contractuales; informar cobertura y limitaciones.
- Ser pura respecto de datos bot-owned: consultas de solo lectura, sin efectos laterales.

## 3. Contrato estructurado propuesto

`contract_version` identifica semántica/formato, no versión de esquema SQL. Decimal monetarios se serializan como strings decimales para no perder precisión en JSON. Timestamps en ISO-8601 UTC con `Z`.

Métricas sugeridas:

| `name` | Valor/unidad | Semántica |
|---|---|---|
| `portfolio.equity` | decimal USDT | Equidad de snapshot o proyección actual, siempre identificando `basis` |
| `portfolio.free_usdt` | decimal USDT | Efectivo libre observado; no necesariamente capital BUY utilizable |
| `portfolio.open_value` | decimal USDT | Valoración de lotes abiertos; métrica de proyección |
| `portfolio.change.{24h,7d,30d}.amount` | decimal USDT | Equity final menos equity baseline |
| `portfolio.change.*.percent` | decimal `%` | Cambio / equity baseline × 100 |
| `portfolio.unrealized_pnl` | decimal USDT / `%` | PnL actual de lotes con base/cobertura completas |
| `portfolio.equity_history` | puntos timestamp + USDT | Serie de snapshots canónicos seleccionados, incluyendo metadata de downsampling |
| `portfolio.attribution.open_positions` | decimal USDT | Cambio del valor abierto atribuible según evidencia de símbolos; no explica toda la equity |
| `portfolio.attribution.unattributed` | decimal USDT o `null` | Remanente solo si total y componentes comparables se conocen; no llamarlo PnL |

Cada métrica usa la envoltura:

```json
{
  "value": "16.66",
  "unit": "USDT",
  "status": "available",
  "reason": null,
  "as_of": "2026-10-16T04:00:00Z",
  "source": "bot.portfolio_snapshots.notes.portfolio_equity_usdt",
  "freshness_seconds": 120
}
```

Status permitidos: `available`, `unavailable`, `stale`, `error`. No codificar `0` para ausencia. `reason` es `null` cuando available y código estable de máquina cuando no available. Un error de consulta/cálculo es distinto de evidencia insuficiente.

## 4. Ejemplo de payload

Ejemplo esquemático, ilustrativo, no dato de producción:

```json
{
  "contract_version": "portfolio.metrics.v1",
  "generated_at": "2026-10-16T04:00:00Z",
  "as_of": "2026-10-16T04:00:00Z",
  "portfolio": {
    "equity": {
      "value": "410.10", "unit": "USDT", "status": "available",
      "reason": null, "basis": "current_projection",
      "as_of": "2026-10-16T03:59:20Z",
      "source": ["bot.bot_healthcheck.details.free_usdt", "bot.position_lots", "bot.portfolio"],
      "freshness_seconds": 40
    },
    "free_usdt": {"value":"26.64","unit":"USDT","status":"available","reason":null,"as_of":"2026-10-16T03:59:20Z","source":"bot.bot_healthcheck.details.free_usdt","freshness_seconds":40},
    "open_value": {"value":"383.46","unit":"USDT","status":"available","reason":null,"as_of":"2026-10-16T03:59:20Z","source":"bot.position_lots+bot.portfolio","freshness_seconds":40}
  },
  "changes": {
    "24h": {
      "status":"available","reason":null,"amount":{"value":"16.66","unit":"USDT"},
      "percent":{"value":"4.35","unit":"percent"},
      "window":{"start":"2026-10-15T04:00:00Z","end":"2026-10-16T04:00:00Z","tolerance_seconds":21600},
      "reference":{"timestamp":"2026-10-15T03:20:00Z","equity_usdt":"383.44"},
      "current":{"timestamp":"2026-10-16T03:59:20Z","equity_usdt":"400.10"}
    },
    "7d":{"status":"unavailable","reason":"baseline_not_found","amount":null,"percent":null,"window":{"target_seconds":604800,"min_age_seconds":518400,"max_age_seconds":691200},"reference":null},
    "30d":{"status":"unavailable","reason":"baseline_not_found","amount":null,"percent":null,"window":{"target_seconds":2592000,"min_age_seconds":2419200,"max_age_seconds":2764800},"reference":null}
  },
  "equity_history": {
    "status":"available","reason":null,"window":{"start":"2026-10-09T04:00:00Z","end":"2026-10-16T04:00:00Z"},
    "source":"bot.portfolio_snapshots","point_count":40,"returned_point_count":40,"downsampled":false,
    "points":[{"timestamp":"2026-10-16T03:59:20Z","equity_usdt":"400.10"}]
  },
  "attribution": {
    "status":"unavailable","reason":"historical_symbol_evidence_missing",
    "basis":"open_position_valuation_only","coverage_percent":null,
    "open_position_contribution_usdt":null,"unattributed_equity_change_usdt":null,
    "limitations":["does_not_attribute_free_usdt_flows","does_not_equal_realized_or_total_trading_pnl"]
  }
}
```

All values above are synthetic structure examples; the numeric values do not claim consistency with each other or observed production.

## 5. Availability and error semantics

Stable reason codes (initial proposal):

- `baseline_not_found`: no valid snapshot inside tolerance.
- `latest_snapshot_stale`: last canonical sample older than maximum age.
- `no_canonical_snapshots`: no usable rows from canonical source.
- `invalid_snapshot_value`: value absent, invalid, non-finite or non-positive.
- `snapshot_limit_truncated`: query cap may have removed a candidate; only report when service can prove it.
- `current_price_missing`, `current_balance_stale`, `incomplete_cost_basis`: current projection evidence incomplete.
- `historical_symbol_evidence_missing`, `historical_symbol_coverage_incomplete`: attribution unavailable.
- `database_unavailable`, `calculation_error`: operational/calculation failure; log correlation ID without exposing SQL/credentials.
- `stale`: data exists but exceeds freshness policy. `unavailable` means there is no defensible value; `0` is a measured value; errors indicate computation could not be completed.

An empty portfolio with complete zero exposure may be a valid numeric zero only if canonical evidence says so. Null must remain null with a reason.

## 6. Historical windows and attribution

- Preserve current horizon tolerances initially (24h=18–30h, 7d=6–8d, 30d=28–32d) only if product owner accepts that these are approximate horizon comparisons. Include exact selected `reference.timestamp`; do not call them exact rolling windows.
- State whether current endpoint is a live projection or canonical latest snapshot. Do not subtract different bases without explicit policy.
- If displaying snapshot-to-snapshot changes, both endpoints must be canonical and same-contract. Do not mix current projection with historical snapshot silently.
- Chart/history may be seven days with a separate density/downsampling policy; its returned metadata must state full interval, first/last returned timestamps, source, and whether visual filtering occurred.
- Symbol attribution compares `notes.symbols` between baseline/current canonical snapshots. For each symbol, require both comparable values or classify coverage as partial. Newly opened/closed symbols and cash/flows require explicit handling. Sum of open-position deltas is a valuation contribution, not trading PnL and not complete account-equity attribution.
- Fees can reduce balances or be charged in non-USDT assets; realized PnL rows only cover recognized lot closures. Deposits, withdrawals and transfers may move equity without being trading profit. Display a remainder only under a stated reconciliation equation and evidence coverage; otherwise set attribution unavailable/partial.

## 7. Compatibilidad con Telegram

El servicio podría reemplazar la preparación de datos, manteniendo inicialmente un adapter de texto que lea los mismos campos y emita las mismas etiquetas/orden/rounding. Un flag de compatibilidad temporal permitiría comparar payload y texto en tests, no dividir fórmulas. No cambiar las palabras `unavailable` ni agregar nuevas líneas visibles hasta autorizar cambio de UX. Reutilizar PNG renderer como adapter visual, agregando ejes solo en un cambio visual posterior.

## 8. Django actual, PWA y JSON futuro

- Dashboard actual: integrar el servicio desde read model/view y templates; sin framework adicional.
- PWA Django: consumir la misma view protegida y HTML/CSS/JS existente; mantener sesión autenticada, CSRF para escrituras y rutas sensibles fuera del alcance público existente. Métricas siguen read-only.
- JSON futuro: serializar el payload de servicio con DRF después de decidir auth, permisos, rate limits, caché, exposición de nombres/símbolos, versionado y política de errores. El endpoint no contiene fórmulas nuevas.
- `contract_version` de payload debe cambiar cuando cambien significado/unidades/semántica; versión URL/API puede evolucionar aparte.

## 9. Estrategia de migración

1. Aprobar semántica y evidencia fuente; confirmar cobertura/retención de snapshots en bot.
2. Implementar servicio pure/read-only y tests Django/PostgreSQL; no migrations si no son necesarias. Cualquier cambio de productor/esquema bot requiere autorización separada.
3. Adaptar Telegram conservando salida actual; comparar old/new internamente en fixtures verificables.
4. Usar servicio en dashboard web; revisar tiempos y límites en tabla realista.
5. Solo luego diseñar endpoint API autenticado y reusar desde PWA.
6. Deprecar fórmula duplicada únicamente después de consistencia demostrada; no cambiar canonical bot data contract en esta fase.

## 10. Decisiones abiertas

- ¿La comparación se define snapshot a snapshot o current live projection menos baseline snapshot?
- ¿Tolerancias actuales son producto aceptado o deben expresarse como rango/label “aprox.”?
- ¿Qué freshness se aplica a snapshot, precio, healthcheck y saldo por separado?
- ¿Quién garantiza conservar 30 días de snapshots: bot, archive consultable o una nueva tabla? No cambiar contrato hasta aprobación.
- ¿Cuál es el mínimo de cobertura histórica por símbolo para atribución y cómo se tratan símbolos nuevos/cerrados?
- ¿Incluir fees, external cash flows o solo valoraciones abiertas? ¿Qué evidencia audita cada término?
- ¿Se expone `partial` como estado adicional o solo `available/unavailable/stale/error` más coverage?
- Política auth/CSRF/cache/retention para API y PWA, y visibilidad para datos financieros.
- ¿Ejes de gráfica deben incluir marcas temporales y escala USDT, y la serie debe ser raw/downsampled/visually filtered?
