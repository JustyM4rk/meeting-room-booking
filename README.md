# Meeting Room Booking Service

Full-stack web service for booking meeting rooms, with an admin panel, an analytics dashboard and an ML-based office load forecast. Built from scratch as a diploma project (Lviv Polytechnic Technological College, 2026).

**Live demo:** https://main-project-nu-ecru.vercel.app (the interface is in Ukrainian)

- Admin account: `admin@test.com` / `admin`
- Regular user: register a new account on the login page

> The demo database is shared and may be reset periodically.

## Features

**Users**
- Registration and login (passwords hashed with bcrypt, JWT access tokens)
- Room catalog with capacity, area, location, description and price per hour
- Booking with extra services (projector, coffee, whiteboard), title, participant count and comment
- Double-booking protection: overlapping bookings for the same room are rejected by the server (`409 Conflict`)
- Edit and cancel your own bookings; filter them by room and by status (upcoming / ongoing / completed)
- Expected office load for the selected weekday and hour, shown in the booking dialog (ML forecast)
- Email notifications on booking creation and status change, plus reminders 1 hour and 10 minutes before the meeting

**Access control (enforced on the server)**
- Every endpoint except login and registration requires a valid JWT
- Users can edit or cancel only their own bookings and cannot approve them; creating rooms, listing users, analytics and model retraining are admin-only

**Admins**
- Create rooms
- Moderate bookings: bookings longer than 3 hours start as `pending` and must be confirmed or rejected
- Edit and delete any booking
- Analytics dashboard: most popular rooms and load by hour of the day

## Tech stack

| Layer | Technologies |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy, Pydantic, passlib (bcrypt) |
| Database | PostgreSQL (Docker Compose) |
| ML & analytics | scikit-learn (Random Forest), pandas |
| Background jobs | FastAPI `BackgroundTasks`, APScheduler, SMTP |
| Frontend | React, TypeScript, Vite, Tailwind CSS, Axios, React Router |
| Deployment | Frontend on Vercel |

## Architecture

```
React SPA (Vercel)
      │  REST / JSON (Axios)
      ▼
FastAPI ──► SQLAlchemy ──► PostgreSQL
   │
   ├─► ML module: Random Forest trained on booking history, saved with pickle
   ├─► Analytics: aggregations with pandas
   └─► Notifications: BackgroundTasks (SMTP) + APScheduler (reminders)
```

## Key design decisions

- **Overlap check.** A new booking is rejected if any booking for the same room satisfies `existing.end > new.start AND existing.start < new.end`. The check runs on the server, not only in the UI.
- **Approval for long bookings.** Bookings over 3 hours are created as `pending`; reminders are scheduled only after an admin confirms them.
- **Authentication.** Login issues a short-lived JWT (`SECRET_KEY` from the environment). The user's role is read from the database on every request, so changing a role takes effect immediately; login errors are generic so the endpoint does not reveal which emails are registered.
- **Non-blocking emails.** Sending over SMTP is slow, so emails go through `BackgroundTasks` and the API responds immediately. Reminders are scheduled jobs that are removed when a booking is rejected or deleted.
- **Load forecast.** A Random Forest regressor takes weekday and hour as features and predicts the expected number of bookings. It was chosen over linear regression because load has sharp, non-linear peaks (specific hours and days of the week). The result is mapped to a status: free / medium / high load.

## API overview

Interactive docs (Swagger UI) are available at `/docs` when the backend is running.

| Method | Endpoint | Description | Access |
|---|---|---|---|
| POST | `/login/` | Log in, returns a JWT | public |
| POST | `/users/` | Register (role is always `user`) | public |
| GET | `/users/` | List users | admin |
| GET | `/rooms/` | List rooms | authenticated |
| POST | `/rooms/` | Create a room | admin |
| GET / POST | `/bookings/` | List / create bookings | authenticated (a user can only book for themselves) |
| PUT / DELETE | `/bookings/{id}` | Update / delete a booking | owner or admin; only admins change `status` |
| GET | `/analytics/dashboard` | Booking statistics | admin |
| GET | `/ml/predict?day=&hour=` | Load forecast for a weekday (0–6) and hour (0–23) | authenticated |
| POST | `/ml/train` | Retrain the model on current data | admin |

## Getting started

**Prerequisites:** Python 3.11+, Node.js 20+, Docker.

### 1. Database

```bash
docker compose up -d postgres-db
```

`docker-compose.yml` also defines MongoDB, RabbitMQ and Redis; the application does not use them yet, so only PostgreSQL needs to run.

### 2. Backend

```bash
cd booking_service
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/booking_db
export SECRET_KEY=$(openssl rand -hex 32)   # required, used to sign JWTs
uvicorn main:app --reload
```

The API starts at http://127.0.0.1:8000 and creates the tables on startup.

Optional: fill the database with demo rooms, users and bookings (from the repository root, with `DATABASE_URL` set):

```bash
PYTHONPATH=booking_service python populate.py
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The API URL defaults to `http://127.0.0.1:8000`; set `VITE_API_URL` to point to another backend.

### 4. Email (optional)

Set `SENDER_EMAIL` and `SENDER_PASSWORD` (for Gmail, an app password) before starting the backend. Without them, emails are printed to the console instead of being sent.

## Tests

```bash
pip install -r requirements-dev.txt
SECRET_KEY=test pytest
```

The tests run against a temporary SQLite database and cover authentication, role checks, booking ownership, the overlap check and status changes.

## Project structure

```
booking_service/   FastAPI app: routes, auth, models, schemas, CRUD, ML, analytics, scheduler, email
tests/             pytest suite (security and booking rules)
frontend/          React + TypeScript SPA
docker-compose.yml PostgreSQL (plus services reserved for future use)
populate.py        Demo data seeding
data_gen.py        Synthetic data generator for the ML model
```

## Roadmap

- Tests for the ML module and analytics; a CI pipeline that runs the test suite
- Rate limiting for the login endpoint
- English localization of the interface
- Alembic migrations instead of the manual `migrate.py` script
- Dockerized backend and frontend

## Author

Markiian Potiuk, Backend Developer. [GitHub](https://github.com/JustyM4rk) · [LinkedIn](https://www.linkedin.com/in/markiian-potiuk-688a50347/)
