# Design Document - django_render

This document details the design decisions, patterns, and data structures implemented in the `django_render` project.

## Design Decisions

### 1. Custom User Model
The project uses a custom `UserProfile` model (extending `AbstractBaseUser` and `PermissionsMixin`) instead of the default Django `User`.
- **Reasoning**: To use `email` as the unique identifier (USERNAME_FIELD) instead of a username, providing a more modern authentication experience.
- **Location**: [`profile/models.py`](profile/models.py).

### 2. API-First Integration
While the project serves HTML templates, it heavily leverages **Django REST Framework (DRF)** for data-driven features.
- **Reasoning**: Decoupling data from representation allows for easier future integration with mobile apps or modern frontend frameworks (React/Vue).
- **Location**: Viewsets in [`currencyconverter/views.py`](currencyconverter/views.py).

### 3. Service Integration via Views
Currently, external API calls (Banco Ciudad, Dolar API) are handled directly within views or helper functions inside `views.py`.
- **Observation**: This is a simple approach but creates tight coupling between the view layer and external service logic.

## Design Patterns

### MVT (Model-View-Template)
The project follows the standard Django MVT pattern:
- **Models**: Define the data structure and business logic (e.g., `ExchangeRate` in [`currencyconverter/models.py`](currencyconverter/models.py)).
- **Views**: Handle request logic and data fetching.
- **Templates**: Standard Django templates using Bootstrap 3 for styling.

### Repository/Service Layer (Missing)
The project currently lacks a formal Service or Repository layer. Logic for fetching exchange rates and processing Telegram messages is embedded in views, which is a target for refactoring to improve testability.

## Database Schema (Key Entities)

### User Management (`profile`)
- **UserProfile**: `email` (PK), `name`, `is_active`, `is_staff`, `password`.

### Currency & Finance (`currencyconverter`)
- **Currency**: `key` (Unique string), `description`.
- **ExchangeRate**: `key` (Unique string), `last_quote` (Decimal), `last_update` (DateTime).

### Communication (`core`)
- **TelegramMessage**: `message_id`, `chat_id`, `from_username`, `message`, `received_at`.

## Authentication & Authorization

- **Session Authentication**: Used for the standard Django admin and web interface.
- **Token Authentication**: Configured in DRF (`rest_framework.authtoken`) for API access.
- **Webhook Security**: The Telegram webhook endpoint validates requests using a secret token passed in the `X-Telegram-Bot-Api-Secret-Token` header.
- **Permissions**: DRF views use `IsAuthenticatedOrReadOnly` to protect write operations while allowing public read access to financial data.
