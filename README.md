# Django CAN-SR

## Configuring dev environment

1. install python3.13
2. Optional (sqlite won't support all features needed) install postgresql
3. Also optional: install [grobid](#grobid) with docker 

**setup virtualenv**

In repo root, 

1. `python -m venv venv`
2. `venv\Scripts\activate` (windows) or `source venv/bin/activate` (linux)
3. `pip install -r requirements.txt -r requirements_dev.txt`

**Set up DB and user**

Depending on which features you're using, postgres is optional, you can also optionally just use the postgres admin user instead too

1. psql -U postgres -c "CREATE ROLE hail_django_db_user with login"
2. psql -U postgres -c "ALTER ROLE hail_django_db_user createdb"
3. createdb -U hail_django_db_user hail_django_db

**populate DB**

1. `python manage.py migrate`
2. `python manage.py loaddata my_app/fixtures/language_models.yaml`
3. `python manage.py runscript my_app.scripts.dev`


## Developing with all dependencies from your phac machine

1. Configure your .env 
    - `USE_SQLITE=True` (postgres may be preferred for certain cases)
    - `GROBID_URL=...` ask around for this
    - LLM:
        - `LLM_MODE=azure`
        - `AZURE_OPENAI_MODE=entra`
        - `AZURE_OPENAI_ENDPOINT=...` ask around for this
    - Figure extraction docint
        - `FIGURE_EXTRACTION_MODE=azure_doc_int`
        - `AZURE_DOC_INT_MODE=entra`
        - `AZURE_DOC_INT_ENDPOINT=...` ask around for this
2. Before running `runserver`, run `az login` and use the "development" project

## General documentation

- See docs written for AI in [copilot-instructions.md](.github/copilot-instructions.md), for code-style, decisions, how to write and run tests, etc. 


## Debugging

As long as you're not doing anything async, you can drop `import IPython; IPython.embed()` anywhere in the code to get an interactive prompt to inspect variables, run code, etc. This is great for tests and live server debugging, but if requests keep happening while you're debugging, the prompt can break and you may have to reset the server (or the parent terminal) process.


## Manually running auto-formatting

In the case your CI is failing due to formatting issues, you can run the following commands to fix them all.

1. `isort src --settings-path pyproject.toml`
2. `black src/ --config pyproject.toml`


# Starter src/.env file


```env
DEBUG=True
ENABLE_DEBUG_TOOLBAR=True
ALLOWED_HOSTS=*
INTERNAL_IPS=127.0.0.1
SECRET_KEY=abcdefg
IS_LOCAL_DEV=True

PHAC_ASPC_SESSION_COOKIE_AGE=99999999 # this doesn't seem to work?
PHAC_ASPC_SESSION_COOKIE_SECURE=0

USE_SQLITE=True
# OR, for postgres:
TEST_DB_NAME=hail_django_db_test
DB_NAME=hail_django_db
DB_USER=hail_django_db_user
DB_PASSWORD=""
DB_HOST=localhost
DB_PORT=5432


LLM_MODE=local

GROBID_URL=dev

USE_IMMEDIATE_TASKS=1
```

# Configuration of advanced features 

## Background tasks

Background tasks use django's new task system. This is swappable based on the env var `USE_IMMEDIATE_TASKS`. 
1. If `USE_IMMEDIATE_TASKS=True`, then tasks will be executed immediately in the same runserver process. This is just for development
2. Otherwise, the app uses the [django-database-tasks](https://github.com/tokibito/django-database-task) library
    - you can view tasks /phac_admin/django_database_task/databasetask/
    - These won't run without a separate CLI process running: `python -m manage run_database_tasks` for a single batch, or setup a continuous process to run them via `python -m manage run_database_tasks --continuous --interval=10`

## Grobid

1. get grobid running, e.g. with docker:
```bash
docker run --rm --init --ulimit core=0 -p 8070:8070 grobid/grobid:0.9.0-crf
```
2. add `GROBID_URL=http://localhost:8070/` to your .env

If you don't want to use grobid, just keep `GROBID_URL=dev`, this will use a dummy client that returns canned responses.

You can check LLM configuration and connection by running `python -m manage check_grobid <path_to_pdf>`, if successful it will print extracted json (raw xml, coordinates, pages) to the console, so you may want to pipe it to a file instead, e.g. `python -m manage check_grobid <path_to_pdf> > output.json`


## LLM configuration

Three modes are supported:

1. using nothing at all (dummy dev client)
2. using local ollama instance
3. using Azure OpenAI

```
LLM_MODE=local
OLLAMA_URL=http://localhost:11434
```

Available models are loaded from the database. From `src/`, populate them with
`python -m manage loaddata my_app/fixtures/language_models.yaml`.

Azure OpenAI supports API-key and Entra authentication:

```env
LLM_MODE=azure
AZURE_OPENAI_MODE=key
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_ENDPOINT=https://example.openai.azure.com
```

You can check LLM configuration and connection by running `python -m manage check_llm` which will attempt to make a test call to the configured LLM

## Calculating code coverage 

From the `src/` directory run the following
1. `coverage run --source=. -m pytest tests/`
2. `coverage html -i`
3. `python -m http.server 1337`
4. visit `http://localhost:1337/htmlcov/` and dig into modules to see which individual line coverage
