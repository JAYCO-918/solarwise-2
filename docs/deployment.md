# Deployment

One process serves the API and the web interface. It needs Python 3.11 or later, a database (a SQLite file by
default, or PostgreSQL), and the built interface (`frontend/dist`).

## 1. From a checkout

```sh
make install          # .venv with the backend; the packages of the interface
make build            # frontend/dist
make run              # http://localhost:8000 with the demonstration   (PORT=8080 make run)
```

Without `make`, and on Windows: see the [README](../README.md). `solarwise serve` listens on 127.0.0.1 by
default; add `--host 0.0.0.0` to accept connections from other machines.

The database is the file `var/solarwise.db` under the directory the server is started in. Its schema is created
at the first start and upgraded at each later start; `solarwise migrate` does the same without starting the
server.

## 2. One container

```sh
docker build -t solarwise-dz .
docker run --rm -p 8000:8000 -v solarwise-data:/data \
    -e SOLARWISE_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" \
    -e SOLARWISE_DEMO_MODE=true \
    solarwise-dz
```

The image builds the interface with Node 22, then installs the backend on `python:3.11-slim` and runs as an
unprivileged user. It runs in production mode, so it refuses to start without a secret key. Data go to a SQLite
file in the `/data` volume unless `DATABASE_URL` names another database. A health check calls `/api/v1/health`.

## 3. With PostgreSQL (Docker Compose)

```sh
cp .env.example .env
#   set SOLARWISE_SECRET_KEY   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
#   set POSTGRES_PASSWORD      python3 -c "import secrets; print(secrets.token_urlsafe(24))"
docker compose up --build
```

Two services: `db` (PostgreSQL 16, data in the `db-data` volume, not published) and `app` (port 8000, or
`SOLARWISE_PORT`). The application waits for the database to be healthy. The database password becomes part of
a URL: use letters, digits, `-` and `_` only.

## 4. Accounts

There is no default account and no default password.

- **Sign-up**: by default the sign-in page offers **Create an account** to whoever can reach the server. The
  account gets the engineer role: it registers its own plants and sees nobody else's. It is never an
  administrator, and its e-mail address is not verified. `SOLARWISE_ALLOW_REGISTRATION=false` removes sign-up.
- **First administrator at start-up**: set `SOLARWISE_BOOTSTRAP_ADMIN_EMAIL` and
  `SOLARWISE_BOOTSTRAP_ADMIN_PASSWORD` (at least 12 characters). The account is created while the installation
  has no administrator; afterwards the two settings are ignored and can be removed. A password that is too weak
  stops the start with a message. If an account that signed up already uses that address, no administrator is
  created and the log says so: choose another address.
- **On the command line**: `solarwise create-user you@example.org --role ADMIN` asks for the password on the
  terminal. In a container:
  `docker compose exec -e SOLARWISE_NEW_PASSWORD=... app solarwise create-user you@example.org --role ADMIN`.
- Afterwards an administrator manages accounts on the **Accounts** page.

## 5. Settings

Environment variables, or a `.env` file in the directory the server is started in. `.env.example` lists them all.
`solarwise check-config` prints the effective configuration and warns about weak settings.

| Variable | Default | Meaning |
|---|---|---|
| `SOLARWISE_ENVIRONMENT` | `development` | `production` requires a secret key, refuses a CORS wildcard and adds HSTS |
| `SOLARWISE_SECRET_KEY` | none | Signs the access tokens; at least 32 characters; mandatory in production |
| `DATABASE_URL` (or `SOLARWISE_DATABASE_URL`) | `sqlite:///./var/solarwise.db` | `postgresql+psycopg://user:password@host:5432/database` for PostgreSQL |
| `SOLARWISE_DEMO_MODE` | `false` | Creates the synthetic reference case and allows entry without an account |
| `SOLARWISE_ALLOW_REGISTRATION` | `true` | Sign-up: visitors create their own account (engineer role, never administrator). `false`: accounts come from an administrator or the command line only |
| `SOLARWISE_BOOTSTRAP_ADMIN_EMAIL`, `..._PASSWORD` | none | First administrator, while the installation has none |
| `SOLARWISE_ALLOWED_HOSTS` | `*` | Host names the server answers to, comma-separated |
| `SOLARWISE_CORS_ORIGINS` | empty | Other origins allowed to call the API from a browser |
| `SOLARWISE_FRAME_ANCESTORS` | `'self'` | Who may show the application in a frame |
| `SOLARWISE_FRONTEND_DIST` | `frontend/dist` of the checkout | Folder of the built interface |
| `SOLARWISE_MAX_UPLOAD_MB` | 25 | Largest accepted upload |
| `SOLARWISE_ACCESS_TOKEN_MINUTES` | 60 | Lifetime of a session |
| `SOLARWISE_LOGIN_MAX_ATTEMPTS`, `..._WINDOW_SECONDS`, `..._LOCKOUT_SECONDS` | 5, 300, 900 | Sign-in throttling |
| `SOLARWISE_EXTERNAL_DATA_ENABLED` | `true` | Allows PVGIS and NASA POWER requests, made only when a user asks |
| `SOLARWISE_EXTERNAL_TIMEOUT_SECONDS` | 20 | Time allowed to those services |
| `SOLARWISE_AI_PROVIDER` | `none` | `openai` or `anthropic`: rephrasing of the explanation; needs `SOLARWISE_AI_API_KEY` and `SOLARWISE_AI_MODEL` |

## 6. For an installation that others can reach

1. `SOLARWISE_ENVIRONMENT=production` and a secret key that is generated, long, and kept out of the repository.
2. **TLS** in a reverse proxy in front of the application. Start the server with `--proxy-headers` and
   `--forwarded-allow-ips <address of the proxy>` so that the logs and the sign-in throttling see the address of
   the client rather than that of the proxy.
3. `SOLARWISE_ALLOWED_HOSTS` set to the public host name.
4. `SOLARWISE_DEMO_MODE=false` if real data are held, or accept that anyone may open the demonstration.
   `SOLARWISE_ALLOW_REGISTRATION=false` if only people you know should have an account: with sign-up open,
   anyone who reaches the server can create one, with an address that is not verified.
5. One instance. The sign-in and sign-up throttling lives in the memory of the process; with several instances,
   limit requests at the proxy as well.
6. If a proxy removes the `Authorization` header, nothing has to be done: the session also travels in
   `X-SolarWise-Token`, and the server log says when that was needed.

## 7. Operating it

| Task | How |
|---|---|
| Health | `GET /api/v1/health` returns `{"status": "ok", "database": "ok"}` |
| Logs | Standard output: one line per request, start-up messages, refused sign-ins with their reason |
| Backup, SQLite | Copy the database file while the server is stopped, or use SQLite's online backup |
| Backup, PostgreSQL | `docker compose exec db pg_dump -U solarwise solarwise > backup.sql` |
| Upgrade | Install the new version and restart: pending migrations are applied at start-up. Back up first |
| Demonstration content | Created at start-up in demonstration mode; `solarwise seed-demo` creates it by hand; existing content is left as it is |

A database that contains tables but no migration history is refused at start-up rather than guessed at: use an
empty database.

## 8. What was verified, and what was not

Verified in the environment the project was built in (Debian 12, Python 3.11, Node 22):

- the checkout installation, the build of the interface and the server;
- the package installed as the image installs it (not in editable mode) and run from another directory, in
  production mode, with a SQLite file and with PostgreSQL 16: start-up, migration, demonstration content,
  first administrator, sign-in, an analysis, the four report formats, and the image's health-check command;
- the whole backend test suite on PostgreSQL 16, and the browser checks that write data.

**Not verified: Docker itself.** No Docker engine was available, so `docker build` and `docker compose up` were
never run. The Dockerfile and the Compose file are written from the steps verified above, but their first real
run may still need a correction. Windows and macOS were not tested either.
