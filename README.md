# Online Cinema API

Online Cinema API is an asynchronous FastAPI application for managing a movie
catalog and the complete purchase flow: account activation, catalog discovery,
favorites and community interactions, shopping carts, orders, Stripe payments,
refunds, and administrative reporting.

## Features

- Email registration and account activation with expiring tokens.
- JWT access and refresh tokens, logout, password change, and password reset.
- User, moderator, and administrator roles.
- Paginated movie catalog with search, filters, and sorting.
- Movie, genre, and actor management for moderators and administrators.
- Favorites, 10-point ratings, likes/dislikes, comments, and replies.
- Email notifications for comment replies, comment likes, and successful payments.
- Shopping carts with duplicate and already-purchased movie protection.
- Orders with price snapshots and purchased/pending movie validation.
- Stripe Checkout, signed webhooks, payment confirmation, history, and refunds.
- A purchased movie list derived from paid orders.
- Administrative cart, order, and payment views with pagination and filters.
- PostgreSQL migrations, idempotent seed data, Redis, Celery Beat, and MailHog.
- Unit and integration tests with an isolated in-memory SQLite database.

## Technology Stack

- Python 3.12
- FastAPI and Pydantic
- SQLAlchemy 2 with async sessions
- PostgreSQL 16 and Alembic
- Stripe Checkout and Stripe CLI
- Redis, Celery, and Celery Beat
- FastAPI Mail and MailHog
- Docker and Docker Compose
- Pytest, pytest-asyncio, pytest-cov, HTTPX, and SQLite
- Ruff, mypy, pre-commit, and GitHub Actions

## Project Structure

```text
.
|-- main.py                         # FastAPI application and routers
|-- requirements.txt                # pip dependencies
|-- requirements-dev.txt            # Local quality and test dependencies
|-- .coveragerc                     # Application coverage settings
|-- ruff.toml                       # Lint and formatting rules
|-- mypy.ini                        # Static type-checking rules
|-- .pre-commit-config.yaml         # Checks executed before a commit
|-- .github/workflows/ci.yml        # GitHub Actions quality and test jobs
|-- docker-compose.yml              # Local service orchestration
|-- Dockerfile
|-- alembic.ini
|-- commands/                       # Container startup scripts
|-- docker/                         # Supporting container images
`-- src/
    |-- config/                     # Settings and dependency providers
    |-- database/
    |   |-- migrations/             # Alembic revisions
    |   |-- models/                 # SQLAlchemy models
    |   |-- seed_data/              # Movie catalog CSV
    |   `-- populate.py             # Idempotent database seed
    |-- notifications/              # Email senders and HTML templates
    |-- routes/                     # FastAPI endpoints
    |-- schemas/                    # Request, response, filter, and pagination models
    |-- security/                   # JWT, passwords, and access dependencies
    |-- services/                   # Shared catalog/account operations
    |-- tasks/                      # Celery tasks
    |-- tests/                      # Unit, integration, helpers, and test doubles
    `-- utils/                      # Shared response utilities
```

## Quick Start With Docker

### Prerequisites

- Docker Desktop with Docker Compose
- A Stripe account and a Stripe test secret key for payment testing
- Stripe CLI installed locally when testing webhook forwarding

### 1. Create the environment file

PowerShell:

```powershell
Copy-Item .env.sample .env
```

Linux, macOS, or Git Bash:

```bash
cp .env.sample .env
```

Set at least the following Docker-compatible values in `.env`:

```dotenv
APP_BASE_URL=http://127.0.0.1:8000

POSTGRES_DB=cinema
POSTGRES_DB_PORT=5432
POSTGRES_USER=cinema_user
POSTGRES_PASSWORD=change_me
POSTGRES_HOST=db

PGADMIN_DEFAULT_EMAIL=admin@example.com
PGADMIN_DEFAULT_PASSWORD=change_me

SECRET_KEY_ACCESS=replace_with_a_long_random_secret
SECRET_KEY_REFRESH=replace_with_another_long_random_secret
JWT_SIGNING_ALGORITHM=HS256

MAILHOG_USER=admin
MAILHOG_PASSWORD=change_me
EMAIL_HOST=mailhog
EMAIL_PORT=1025
EMAIL_HOST_USER=testuser
EMAIL_HOST_PASSWORD=test_password
EMAIL_USE_TLS=False

CELERY_BROKER_URL=redis://redis:6379/0

STRIPE_SECRET_KEY=sk_test_your_key_here
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret
STRIPE_CURRENCY=usd
STRIPE_SUCCESS_URL=http://127.0.0.1:8000/payment-success?session_id={CHECKOUT_SESSION_ID}
STRIPE_CANCEL_URL=http://127.0.0.1:8000/payment-canceled
```

### 2. Configure the local Stripe signing secret

Stripe cannot deliver Dashboard webhook events directly to `localhost`. Obtain
the Stripe CLI signing secret for the same test account used by
`STRIPE_SECRET_KEY`:

```bash
stripe listen --print-secret --api-key sk_test_your_key_here
```

Save the returned `whsec_...` value as `STRIPE_WEBHOOK_SECRET` in `.env`.
The `stripe_cli` Compose service will forward the supported Checkout and refund
events to `/theater/payments/webhook/`.

### 3. Start the application

```bash
docker compose up --build
```

The `migrator` service automatically runs all Alembic migrations and then seeds
the three user groups and the movie catalog. Seeding is idempotent, so existing
movies are not duplicated on later starts.

Run in the background when interactive logs are not needed:

```bash
docker compose up --build -d
```

Inspect the main services:

```bash
docker compose logs -f web stripe_cli celery_worker celery_beat
```

Stop the services without removing database data:

```bash
docker compose down
```

To remove PostgreSQL and pgAdmin volumes and start with empty persistent data:

```bash
docker compose down -v
```

The last command permanently removes local container data.

## Local Service URLs

| Service | URL | Notes |
| --- | --- | --- |
| API | `http://127.0.0.1:8000` | FastAPI application |
| Swagger UI | `http://127.0.0.1:8000/docs` | Interactive OpenAPI documentation |
| ReDoc | `http://127.0.0.1:8000/redoc` | Read-only API reference |
| OpenAPI JSON | `http://127.0.0.1:8000/openapi.json` | OpenAPI 3.1 schema |
| MailHog | `http://127.0.0.1:8025` | Uses `MAILHOG_USER` and `MAILHOG_PASSWORD` |
| pgAdmin | `http://127.0.0.1:3333` | Uses the pgAdmin values from `.env` |
| PostgreSQL | `127.0.0.1:5432` | Exposed for local database clients |
| Redis | `127.0.0.1:6379` | Celery broker and result backend |

When registering the PostgreSQL server in pgAdmin, use `db` as the host and
`5432` as the port because pgAdmin runs inside the Compose network.

## Environment Variables

| Variable | Purpose |
| --- | --- |
| `APP_BASE_URL` | Public backend base URL used in email links |
| `POSTGRES_DB` | PostgreSQL database name |
| `POSTGRES_DB_PORT` | PostgreSQL port, normally `5432` |
| `POSTGRES_USER` | PostgreSQL user |
| `POSTGRES_PASSWORD` | PostgreSQL password |
| `POSTGRES_HOST` | `db` in Docker, usually `localhost` outside Docker |
| `PGADMIN_DEFAULT_EMAIL` | pgAdmin login email |
| `PGADMIN_DEFAULT_PASSWORD` | pgAdmin login password |
| `SECRET_KEY_ACCESS` | Secret used to sign access tokens |
| `SECRET_KEY_REFRESH` | Separate secret used to sign refresh tokens |
| `JWT_SIGNING_ALGORITHM` | JWT algorithm, normally `HS256` |
| `MAILHOG_USER` | MailHog web UI username |
| `MAILHOG_PASSWORD` | MailHog web UI password |
| `EMAIL_HOST` | `mailhog` in Docker or an SMTP hostname |
| `EMAIL_PORT` | SMTP port, `1025` for MailHog |
| `EMAIL_HOST_USER` | SMTP username |
| `EMAIL_HOST_PASSWORD` | SMTP password |
| `EMAIL_USE_TLS` | Whether SMTP TLS is enabled |
| `CELERY_BROKER_URL` | Redis URL used by Celery |
| `STRIPE_SECRET_KEY` | Stripe test or live secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe endpoint/CLI signing secret |
| `STRIPE_CURRENCY` | Checkout currency, for example `usd` |
| `STRIPE_SUCCESS_URL` | Frontend success URL; preserve `{CHECKOUT_SESSION_ID}` |
| `STRIPE_CANCEL_URL` | Frontend cancellation URL |

## Authentication

### Registration and activation

Register a user with `POST /accounts/register/`:

```json
{
  "email": "user@example.com",
  "password": "StrongPass1!"
}
```

Passwords must contain at least eight characters, one uppercase letter, one
lowercase letter, one digit, and one of `@$!%*?&#`.

Open MailHog and follow the activation link, or submit the email and token to
`POST /accounts/activate/`. Activation and password-reset tokens expire after
24 hours. Celery Beat removes expired tokens every hour.

### Login and protected requests

`POST /accounts/login/` accepts JSON:

```json
{
  "email": "user@example.com",
  "password": "StrongPass1!"
}
```

The response contains `access_token`, `refresh_token`, and `token_type`. In
Postman, add the access token as a Bearer token, which sends:

```http
Authorization: Bearer <access_token>
```

The login endpoint accepts a JSON body, not OAuth2 form data. Authenticated
examples therefore assume that Postman or another API client adds the Bearer
header directly.

Access tokens are valid for 60 minutes. Refresh tokens are stored in the
database and are valid for seven days. Use `POST /accounts/refresh/` to obtain a
new access token and `POST /accounts/logout/` to revoke a refresh token.

### Roles

| Role | Permissions |
| --- | --- |
| `user` | Catalog, favorites, interactions, cart, orders, and own payments |
| `moderator` | User permissions plus movie, genre, and actor management |
| `admin` | Moderator permissions plus users, carts, orders, and payment administration |

The seed creates role records but does not create privileged users. For local
development, register and activate the first admin, then promote it directly in
PostgreSQL:

```bash
docker compose exec db psql -U cinema_user -d cinema -c "UPDATE users SET group_id = (SELECT id FROM user_groups WHERE name = 'ADMIN') WHERE email = 'admin@example.com';"
```

Replace the database credentials and email with the values from `.env`. This is
a local bootstrap operation, not an application endpoint. After bootstrapping,
use `POST /admin/users/{user_id}/group/` with `user`, `moderator`, or `admin` to
manage other users.

## API Overview

Detailed request fields, query constraints, response schemas, examples, and
error responses are available in Swagger UI and ReDoc.

### Accounts

| Method | Path | Access | Action |
| --- | --- | --- | --- |
| `POST` | `/accounts/register/` | Public | Register and send activation email |
| `GET`, `POST` | `/accounts/activate/` | Public | Activate an account with email and token |
| `POST` | `/accounts/resend-activation/` | Public | Replace and resend an activation token |
| `POST` | `/accounts/password-reset/request/` | Public | Send a password-reset email |
| `POST` | `/accounts/reset-password/complete/` | Public | Set a password with a reset token |
| `POST` | `/accounts/login/` | Public | Issue access and refresh tokens |
| `POST` | `/accounts/refresh/` | Refresh token | Issue a new access token |
| `POST` | `/accounts/logout/` | Refresh token | Revoke the supplied refresh token |
| `POST` | `/accounts/change-password/` | User | Change password with the old password |

### Catalog and community

| Method | Path | Access | Action |
| --- | --- | --- | --- |
| `GET` | `/theater/movies/` | Public | Search, filter, sort, and paginate movies |
| `GET` | `/theater/movies/{movie_uuid}/` | Public | Get detailed movie information |
| `POST`, `PATCH`, `DELETE` | `/theater/movies/...` | Moderator/Admin | Manage movies |
| `GET` | `/theater/movies/purchased/` | User | List unique movies from paid orders |
| `GET` | `/theater/genres/` | Public | List genres with movie counts |
| `POST`, `GET`, `PATCH`, `DELETE` | `/theater/genres/...` | Moderator/Admin for mutations | Manage genres |
| `GET` | `/theater/actors/` | Public | Search and paginate actors |
| `POST`, `GET`, `PATCH`, `DELETE` | `/theater/actors/...` | Moderator/Admin for mutations | Manage actors |
| `GET` | `/theater/favorites/` | User | Filter, sort, and paginate favorites |
| `POST`, `DELETE` | `/theater/favorites/{movie_uuid}/` | User | Add or remove a favorite |
| `GET`, `POST` | `/theater/movies/{movie_uuid}/comments/` | Public/User | List or create movie comments |
| `GET`, `PATCH`, `DELETE` | `/theater/comments/{comment_uuid}/` | Public/Owner/Moderator | Read, update, or delete a comment |
| `GET`, `POST` | `/theater/comments/{comment_uuid}/replies/` | Public/User | List or create direct replies |
| `GET` | `/theater/movies/{movie_uuid}/reactions/` | Public | Get movie like/dislike totals |
| `GET`, `PUT`, `DELETE` | `/theater/movies/{movie_uuid}/reaction/` | User | Read, set, or remove own movie reaction |
| `GET` | `/theater/comments/{comment_uuid}/reactions/` | Public | Get comment like/dislike totals |
| `GET`, `PUT`, `DELETE` | `/theater/comments/{comment_uuid}/reaction/` | User | Read, set, or remove own comment reaction |
| `GET` | `/theater/movies/{movie_uuid}/ratings/` | Public | Get average score and rating count |
| `GET`, `PUT`, `DELETE` | `/theater/movies/{movie_uuid}/rating/` | User | Read, set, or remove own 1-10 rating |

Deleting a movie is rejected when it is currently in a cart or has been
purchased. Adding a movie to a cart is rejected when the current user already
owns it.

### Cart, orders, and payments

| Method | Path | Access | Action |
| --- | --- | --- | --- |
| `GET`, `DELETE` | `/theater/cart/` | User | View or clear the current cart |
| `POST`, `DELETE` | `/theater/cart/items/{movie_uuid}/` | User | Add or remove a cart movie |
| `POST` | `/theater/orders/` | User | Create a pending order from eligible cart items |
| `GET` | `/theater/orders/` | User | List own orders |
| `GET` | `/theater/orders/{order_id}/` | User | Get an owned order |
| `POST` | `/theater/orders/{order_id}/cancel/` | User | Cancel an owned pending order |
| `POST` | `/theater/payments/orders/{order_id}/checkout/` | User | Create Stripe Checkout and return its URL |
| `GET` | `/theater/payments/` | User | List own payment history |
| `GET` | `/theater/payments/{payment_id}/` | User | Get an owned payment and price snapshots |
| `GET` | `/theater/payments/confirmation/` | User | Confirm status by `session_id` after redirect |
| `POST` | `/theater/payments/{payment_id}/refund/` | User | Request a refund for a successful payment |
| `POST` | `/theater/payments/webhook/` | Stripe | Validate and process signed Stripe events |

### Administration

| Method | Path | Filters/body | Action |
| --- | --- | --- | --- |
| `GET` | `/admin/carts/` | `page`, `per_page` | List user carts |
| `GET` | `/admin/users/{user_id}/cart/` | Path user ID | Inspect one user cart |
| `GET` | `/admin/orders/` | User, date, status, pagination | List and filter all orders |
| `GET` | `/admin/payments/` | User, date, status, pagination | List and filter all payments |
| `POST` | `/admin/users/{user_id}/group/` | `group_name` | Change a user role |
| `POST` | `/admin/users/{user_id}/activate/` | Path user ID | Manually activate an account |

All `/admin` endpoints require the `admin` role.

## Filtering and Pagination

Movie and favorite lists support:

- `page`, `per_page`
- `search` across title, description, actor, and director
- repeated `years` values plus `year_from` and `year_to`
- `imdb_min`, `imdb_max`, `price_min`, and `price_max`
- repeated `genre_ids` and `certification_ids`
- `sort_by`: `newest`, `name`, `year`, `price`, `imdb`, or `popularity`
- `sort_order`: `asc` or `desc`

List-valued parameters are repeated in the query string, for example:

```text
/theater/movies/?genre_ids=1&genre_ids=3&year_from=2020&sort_by=price&sort_order=asc
```

Admin order and payment lists support `user_id`, `date_from`, `date_to`,
`status`, `page`, and `per_page`. Dates use `YYYY-MM-DD` and are interpreted as
inclusive UTC dates. Order statuses are `pending`, `paid`, and `canceled`.
Payment statuses are `pending`, `successful`, `canceled`, and `refunded`.

Paginated responses contain `prev_page`, `next_page`, `total_pages`, and
`total_items`.

## Purchase and Stripe Payment Flow

1. Authenticate and send the access token as a Bearer token.
2. Add movies with `POST /theater/cart/items/{movie_uuid}/`.
3. Create an order with `POST /theater/orders/`. Purchased movies and movies in
   another pending order are excluded, and the cart is cleared after the order
   snapshot is created.
4. Create Checkout with
   `POST /theater/payments/orders/{order_id}/checkout/`. Prices are revalidated
   against the current catalog before Stripe line items and payment snapshots
   are created.
5. Open the returned `checkout_url` and complete payment in Stripe test mode.
6. Stripe sends a signed webhook. A successful event changes the payment to
   `successful`, changes the order to `paid`, and schedules a confirmation email.
7. The frontend reads `session_id` from the success redirect and makes an
   authenticated request to
   `GET /theater/payments/confirmation/?session_id=...`. This endpoint also
   reconciles a paid Stripe session if webhook delivery was delayed.
8. The movie becomes available from `GET /theater/movies/purchased/`.

This repository contains the API only. It does not serve `/payment-success` or
`/payment-canceled` HTML pages. Configure `STRIPE_SUCCESS_URL` and
`STRIPE_CANCEL_URL` to point to frontend pages when a frontend is available. A
404 after Stripe redirects to the default local success URL does not by itself
mean the payment failed; check the webhook logs and payment status.

The webhook is the source of truth for asynchronous success, failure,
expiration, and refund completion. Calling the refund endpoint returns `202`
while the local payment remains successful; the signed refund webhook changes
the payment to `refunded` and the order to `canceled`.

Verify local webhook forwarding with:

```bash
docker compose logs -f stripe_cli web
```

A successful delivery appears as a `POST /theater/payments/webhook/` response
with status `200`.

## Email and Celery

MailHog captures activation, password-reset, comment notification, and payment
confirmation emails in local development. The web UI is protected with the
credentials from `.env`.

Celery uses Redis as both broker and result backend. Celery Beat runs
`delete_expired_tokens` at the start of every UTC hour to remove expired account
activation and password-reset tokens. Both Celery containers run as the
non-root `appuser` created by the application image.

## Database and Seed Data

Apply migrations manually inside the running web container:

```bash
docker compose exec web alembic -c alembic.ini upgrade head
```

Create a new migration after changing models:

```bash
docker compose exec web alembic -c alembic.ini revision --autogenerate -m "describe change"
```

Run the idempotent seed manually:

```bash
docker compose exec web python -m src.database.populate
```

The seed creates missing role records and imports the bundled IMDb CSV in
batches. Existing movies are identified by title, release year, and runtime and
are skipped.

## Running Tests

Create and activate a local virtual environment, install the development
dependencies, and run:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

Useful subsets:

```bash
python -m pytest -m unit
python -m pytest -m integration
python -m pytest src/tests/test_integration/test_payments.py -q
```

Tests set `ENVIRONMENT=testing` and use a fresh in-memory SQLite schema for each
test. They do not modify the PostgreSQL database from `.env`. Email and Stripe
operations are replaced with test doubles.

To include a coverage report:

```bash
python -m pytest --cov=src --cov-report=term-missing
```

## Code Quality and CI

Run the same quality checks locally that GitHub Actions runs for every pull
request to `main` and every push to `main`:

```bash
python -m ruff check main.py src
python -m ruff format --check main.py src
python -m mypy main.py src
```

Apply safe lint fixes and formatting before committing:

```bash
python -m ruff check main.py src --fix
python -m ruff format main.py src
```

Install the Git hook once in each local clone:

```bash
python -m pre_commit install
```

After installation, Ruff checks and formats staged Python files before each
commit. Run the hooks against the entire repository at any time with:

```bash
python -m pre_commit run --all-files
```

The workflow in `.github/workflows/ci.yml` contains two independent jobs:
`Code quality` runs Ruff and mypy, while `Tests` runs the complete test suite
and generates terminal and XML coverage reports.

## Running Without Docker

Docker Compose is the recommended setup because PostgreSQL, Redis, MailHog,
Celery, and Stripe CLI are already wired together. To run only the API locally:

PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
alembic -c alembic.ini upgrade head
python -m src.database.populate
uvicorn main:app --reload
```

Set `POSTGRES_HOST=localhost` and point the email, Redis, and Stripe settings at
services reachable from the host. Run Celery in separate terminals when account
token cleanup is required:

```bash
celery -A src.celery_app.celery_app:celery_app worker --loglevel=info
celery -A src.celery_app.celery_app:celery_app beat --loglevel=info
```
