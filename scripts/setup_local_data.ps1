[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
$Container = 'telesale-postgres'
$Image = 'postgres:16'

function Invoke-Migration([string]$Script, [string[]]$Arguments = @()) {
    & $Python -X utf8 $Script @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Failed to run $Script. See the output above." }
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw 'Create and install .venv first (README section 3.1).'
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Install Docker Desktop first (README section 3.1).'
}

Push-Location -LiteralPath $ProjectRoot
try {
    if (-not (Test-Path -LiteralPath '.env' -PathType Leaf)) {
        throw 'Create .env from .env.example first (README section 3.1).'
    }

    @'
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv('.env')
url = 'postgresql+psycopg2://telesale:telesale_dev_password@localhost:5432/telesale?sslmode=disable'
if os.environ.get('DATABASE_URL') != url:
    raise SystemExit('Use the local DATABASE_URL from .env.example. Check for a shell override.')
if os.environ.get('KNOWLEDGE_BACKEND', 'chroma').strip().lower() != 'chroma':
    raise SystemExit('Set KNOWLEDGE_BACKEND=chroma in .env and clear any shell override.')
if Path(os.environ.get('CHROMA_DB_DIR', 'data/chroma_db')).resolve() != Path('data/chroma_db').resolve():
    raise SystemExit('Set CHROMA_DB_DIR=data/chroma_db in .env and clear any shell override.')
if os.environ.get('CHROMA_EMBEDDING_MODEL', 'keepitreal/vietnamese-sbert').strip() != 'keepitreal/vietnamese-sbert':
    raise SystemExit('Use the default Chroma embedding model (keepitreal/vietnamese-sbert).')
'@ | & $Python -X utf8 -
    if ($LASTEXITCODE -ne 0) { throw 'Local environment check failed. See the output above.' }

    Write-Host '[1/3] Starting PostgreSQL...'
    $DockerOS = docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0 -or $DockerOS -ne 'linux') {
        throw 'Start Docker Desktop in Linux containers mode and retry.'
    }
    $Found = docker ps -a --filter "name=^/$Container$" --format '{{.Names}}'
    if ($LASTEXITCODE -ne 0) { throw 'Could not list Docker containers.' }
    if ($Found -eq $Container) {
        $ExistingImage = docker inspect --format '{{.Config.Image}}' $Container
        if ($LASTEXITCODE -ne 0 -or $ExistingImage -ne $Image) {
            throw "$Container already exists with a different image. Check it before retrying."
        }
        $Running = docker inspect --format '{{.State.Running}}' $Container
        if ($LASTEXITCODE -ne 0) { throw "Could not inspect $Container." }
        if ($Running -ne 'true') {
            docker start $Container
            if ($LASTEXITCODE -ne 0) { throw "Could not start $Container. Check whether port 5432 is free." }
        }
    } else {
        docker run -d --name $Container `
            -e POSTGRES_USER=telesale -e POSTGRES_PASSWORD=telesale_dev_password -e POSTGRES_DB=telesale `
            -p '127.0.0.1:5432:5432' -v 'telesale_pgdata:/var/lib/postgresql/data' $Image
        if ($LASTEXITCODE -ne 0) { throw "Could not create $Container. Check whether port 5432 is free." }
    }

    $PublishedPort = docker port $Container '5432/tcp'
    if ($LASTEXITCODE -ne 0 -or $PublishedPort -notcontains '127.0.0.1:5432') {
        throw "$Container must publish PostgreSQL on 127.0.0.1:5432. Check docker port $Container."
    }
    $ReadyDeadline = (Get-Date).AddSeconds(60)
    do {
        docker exec $Container pg_isready -h 127.0.0.1 -U telesale -d telesale -q
        if ($LASTEXITCODE -eq 0) { break }
        if ((Get-Date) -ge $ReadyDeadline) { throw "PostgreSQL did not become ready. See: docker logs $Container" }
        Start-Sleep -Seconds 1
    } while ($true)

    Write-Host '[2/3] Preparing database schema and sample data...'
    $CatalogState = @'
import os
from runpy import run_path

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

load_dotenv('.env')
tables = set(run_path('scripts/migrate_catalog.py')['Base'].metadata.tables)
engine = create_engine(os.environ['DATABASE_URL'], connect_args={'connect_timeout': 5})
try:
    with engine.connect() as conn:
        present = tables.intersection(inspect(conn).get_table_names())
        if not present:
            print('seed')
        elif present == tables and conn.execute(text(
            'SELECT EXISTS (SELECT 1 FROM products) AND EXISTS (SELECT 1 FROM customers)'
        )).scalar_one():
            print('existing')
        else:
            raise SystemExit('Local database has an incomplete catalog/CRM. Inspect it before retrying; no data was reset.')
except SQLAlchemyError:
    raise SystemExit('Cannot connect to the local PostgreSQL database with .env credentials.')
finally:
    engine.dispose()
'@ | & $Python -X utf8 -
    if ($LASTEXITCODE -ne 0) { throw 'Database check failed. See the output above.' }
    if ($CatalogState -eq 'seed') {
        Invoke-Migration 'scripts/migrate_catalog.py'
    } else {
        Invoke-Migration 'scripts/migrate_catalog.py' @('--orders-only')
    }
    Invoke-Migration 'scripts/migrate_app_data.py'
    Invoke-Migration 'scripts/migrate_voice.py'
    Invoke-Migration 'scripts/migrate_learning.py'

    Write-Host '[3/3] Preparing local Chroma policy data...'
    Invoke-Migration 'scripts/ingest_policy.py' @('--if-empty')
    Write-Host 'Local data ready. PostgreSQL is on 127.0.0.1:5432; Chroma is in data/chroma_db.'
} finally {
    Pop-Location
}
