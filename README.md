# GlobalConnect Platform (Django + SQLite)

An integrated platform combining:
- Professional networking (LinkedIn-style feed, connect, like, comment, share)
- Job discovery and hiring (Naukri-style opportunities + direct apply)
- Event hosting and joining (Meetup-style events with ticket booking)
- Promotion/SEO module (account boost, post boost, campaign posting)

Includes trust-score based access controls and face/liveness verification gate.

## Core Features

- Authentication with human/liveness verification workflow
  - Frontend webcam capture + challenge confirmation
  - Luxand liveness API integration via `LUXAND_API_TOKEN` (free-tier supported)
  - If API token is not set, challenge flow still gates verification state for local/dev testing
- Trust Score mechanism (0-100)
  - Rewards verification, complete profile, and network growth
  - Used to unlock sensitive modules:
    - Event hosting: trust score >= 65 and verified human
    - Promotion posting: trust score >= 70 and verified human
- Networking feed
  - Create posts, like, comment, share
  - Suggested users + connect requests
  - Home page shows latest posts globally
- Opportunities tab
  - Post jobs and apply directly from network users
  - Application counts visible on opportunities
- Events tab
  - Verified users/companies can host events
  - Users can join events and book tickets
- Promotions tab
  - SEO/promotion campaigns with budget and campaign content

## Tech Stack

- Backend: Django
- Frontend: Django templates + HTML/CSS/JS
- Database: SQLite

## Local Setup

1) Install dependencies:

```bash
pip install -r requirements.txt
```

2) (Optional but recommended) set environment variables:

```bash
set DJANGO_SECRET_KEY=replace-this
set DJANGO_DEBUG=True
set LUXAND_API_TOKEN=your_luxand_token
```

3) Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

4) Create admin user:

```bash
python manage.py createsuperuser
```

5) Start server:

```bash
python manage.py runserver
```

App entry points:
- Signup: `/signup/`
- Login: `/login/`
- Home (network feed): `/`
- Opportunities: `/opportunities/`
- Events: `/events/`
- Promotions: `/promotions/`

## Deployment Notes

- Run production settings with:
  - `DJANGO_DEBUG=False`
  - strong `DJANGO_SECRET_KEY`
- Collect static assets:

```bash
python manage.py collectstatic --noinput
```

- Example Gunicorn command:

```bash
gunicorn Baadme_Sochenge.wsgi:application --bind 0.0.0.0:8000
```

## Important Security Note

For production-grade anti-spoof protection, use:
- Strong liveness provider configuration
- HTTPS only
- Rate limiting and lockout policies
- Optional secondary verification checks for high-risk flows
