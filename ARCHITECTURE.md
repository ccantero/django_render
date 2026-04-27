# Project Architecture - django_render

This document provides a high-level overview of the technical architecture of the `django_render` project.

## Tech Stack

- **Framework**: [Django](https://www.djangoproject.com/) (Python-based web framework).
- **API**: [Django REST Framework (DRF)](https://www.django-rest-framework.org/) for building web APIs.
- **Database**: 
  - **Development**: SQLite (local development convenience).
  - **Production**: PostgreSQL (standard relational database).
- **Infrastructure**:
  - **Web Server**: [Gunicorn](https://gunicorn.org/) (WSGI HTTP Server).
  - **Static Files**: [WhiteNoise](http://whitenoise.evans.io/) for serving static files directly from the web server.
  - **Hosting**: Optimized for [Render.com](https://render.com/).
- **API Documentation**: [drf-spectacular](https://github.com/tfranzel/drf-spectacular) (OpenAPI 3.0).

## Request/Response Lifecycle

1. **Entry Point**: The request is received by the web server (Gunicorn in production).
2. **Middleware**:
   - `SecurityMiddleware`: Handles HTTPS redirects and security headers.
   - `WhiteNoiseMiddleware`: Intercepts requests for static assets.
   - Standard Django middleware: `Session`, `Common`, `Csrf`, `Authentication`, `Message`, and `XFrameOptions`.
3. **URL Routing**: `django_render/urls.py` dispatches the request to the appropriate application based on the path.
4. **Views**: 
   - **TemplateViews**: Serve HTML content (Core, CurrencyConverter).
   - **ViewSets**: Provide RESTful endpoints for data (Profile, CurrencyConverter).
   - **Functional Views**: Handle specific logic like Telegram webhooks or rate updates.
5. **Data Access**: Views interact with models using the Django ORM.
6. **Response**: Data is returned as rendered HTML (Templates) or JSON (DRF).

## External Services Integration

The project integrates with several external services to provide real-time financial data and communication:

- **Banco Ciudad API**: Fetches ARS/UVA exchange rates.
- **Dolar API**: Retrieves official and blue USD/ARS exchange rates.
- **Telegram Bot API**: Receives updates via webhooks and sends messages to users.

## Project Structure

```text
├── core/               # Main application: landing pages, telegram webhook
├── currencyconverter/  # Finance logic: exchange rates, UVA calculations
├── profile/            # Custom User model and authentication logic
├── investments/        # (Placeholder) Future investment tracking logic
├── django_render/      # Project configuration and settings
├── static/             # Global frontend assets (CSS, JS, Images)
├── templates/          # Global HTML templates
└── manage.py           # Django management CLI
```

## Data Flow Diagram (Conceptual)

```text
[User Browser] <--> [Django App] <--> [PostgreSQL]
                        ^
                        |
            [External Financial APIs]
                        |
            [Telegram Bot API]
```
