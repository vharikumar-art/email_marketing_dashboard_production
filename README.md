# Email Dashboard API

FastAPI backend for the email marketing dashboard.

## Production Setup

1. Create a Python 3.11 virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and set real values.
4. Generate an `ENCRYPTION_KEY`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

5. Run locally:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

6. Production command for VPS:

```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers 2 --bind 0.0.0.0:8000 --timeout 120
```

## Hostinger VPS Notes

- Use MongoDB Atlas or a managed MongoDB instance.
- Set `ALLOWED_ORIGINS` to only your frontend domain.
- Keep `.env` outside git/upload sharing.
- Put Nginx in front of port `8000` and enable SSL.
- Optional: add Redis and set `REDIS_URL` for shared cache across workers.

## Clean Structure

```text
app/main.py        FastAPI app bootstrap, middleware, exception handlers
app/api/router.py  Central API router registration
app/api/routes.py  API endpoint handlers
app/auth.py        Authentication and authorization dependencies
app/cache.py       Dashboard/cache helpers
app/database.py    MongoDB connection and indexes
app/schemas.py     Pydantic request/response models
static/            Uploaded/default images served by the API
docs/              API and database documentation
requirements.txt   Production Python dependencies
```

The test folders, scratch files, local virtual environments, logs, and secret files were removed from this production copy.

The API is now registered through `app.include_router(api_router)`, so future endpoints can be moved into smaller route files without changing `app/main.py`.
