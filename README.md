# Django Render Project

A robust Django-based application designed for currency tracking, financial calculations, and Telegram bot integration. Optimized for deployment on Render.com.

## 🚀 Features

- **Currency Converter**: Real-time tracking of ARS, USD (Official & Blue), and UVA rates.
- **Telegram Bot Integration**: Webhook-based listener for automated message handling.
- **REST API**: Fully documented API using OpenAPI 3.0 (drf-spectacular).
- **Production Ready**: Configured with WhiteNoise for static files and Gunicorn for performance.

## 🛠️ Prerequisites

- Python 3.9+
- pip & venv
- PostgreSQL (optional for local, defaults to SQLite)

## 💻 Local Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd django_render
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Variables**:
   Create a `.env` file in the root directory (refer to `django_render/settings.py` for required keys):
   ```env
   SECRET_KEY=your-secret-key
   CC_DEBUG=True
   TUTORIAL_BOT_TOKEN=your-telegram-token
   TELEGRAM_WEBHOOK_TOKEN=your-webhook-secret
   ```

5. **Run Migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Create a Superuser**:
   ```bash
   python manage.py createsuperuser
   ```

7. **(Optional) Populate Database**:
   ```bash
   python populate_database.py
   ```

## 🏃 Execution

Start the development server:
```bash
python manage.py runserver
```
The application will be available at `http://127.0.0.1:8000`.

## 🧪 Testing

Run the test suite using `pytest`:
```bash
pytest
```

## 📚 API Documentation

Once the server is running, you can access the interactive API documentation at:
- **Swagger UI**: `http://127.0.0.1:8000/api/docs`
- **Schema (YAML)**: `http://127.0.0.1:8000/api/schema`
