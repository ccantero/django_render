# Project Roadmap & TODO List

This list tracks the prioritized tasks for modernizing and improving the `django_render` project.

## 🔴 [URGENTE] Seguridad y Bugs

- [x] **Validation of Environment Variables**: Implement a strict check on startup to ensure all required `.env` variables are present (especially `SECRET_KEY` and Telegram tokens).
- [ ] **Telegram Webhook Security**: Ensure `TELEGRAM_WEBHOOK_TOKEN` is rotated and verified correctly in all environments.
- [ ] **Error Handling in External APIs**: Add robust `try-except` blocks around `requests.get` calls in `currencyconverter/views.py` to prevent 500 errors when external services are down.
- [ ] **Fix Django Version Mismatch**: Resolve the discrepancy between `requirements.txt` (3.2.25) and `settings.py` metadata (4.1.3).

## 🟡 [HIGH] Refactor de Deuda Técnica y Dependencias

- [ ] **Service Layer Implementation**: Refactor `currencyconverter/views.py` and `core/views.py`. Move external API logic (Banco Ciudad, Dolar API, Telegram) into dedicated service classes.
- [ ] **Dependency Update**: Upgrade Django to 4.2 LTS and update all related packages (DRF, drf-spectacular).
- [ ] **Investments App Implementation**: The `investments/` app is currently a placeholder. Design and implement the core models and views for investment tracking.
- [ ] **Improve Test Coverage**: Increase unit test coverage for views and service logic using `pytest`.
- [ ] **Database Migrations Cleanup**: Verify and consolidate migrations to ensure a clean state for new developers.

## 🔵 [BACKLOG] Nuevas Funcionalidades y Performance

- [ ] **Caching Layer**: Implement Redis caching for exchange rates to reduce the number of external API calls and improve response times.
- [ ] **Frontend Modernization**: Replace Bootstrap 3 with a more modern CSS framework (Tailwind CSS or Bootstrap 5) and improve the responsive design.
- [ ] **Multi-Currency Support**: Expand the `currencyconverter` to support more fiat currencies and potentially cryptocurrencies.
- [ ] **Advanced Telegram Bot Features**: Implement stateful conversations (using a FSM) and richer message formats (inline buttons, charts).
- [ ] **Performance Monitoring**: Integrate with a tool like Sentry or New Relic for real-time error tracking and performance monitoring.
- [ ] **Auto Refresh**: Implement JS to auto-refresha and prevent spin down