"""Run opt-in PostgreSQL tests in a newly created disposable database."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from sqlalchemy import create_engine, text
from telesale_agent.adapters.db.app_schema import create_app_engine

production = create_app_engine()
if production.url.host != 'localhost' or production.url.database != 'telesale':
    raise RuntimeError('Unexpected database target')
name = 'btc_audit_' + uuid4().hex
assert re.fullmatch(r'btc_audit_[0-9a-f]{32}', name)
admin = create_engine(production.url.set(database='postgres'), isolation_level='AUTOCOMMIT', hide_parameters=True)
report = {'test_database': name, 'production_database': 'telesale', 'created': False}

def snapshot():
    with production.connect() as connection:
        connection.execute(text('SET TRANSACTION READ ONLY'))
        rows = connection.execute(text('SELECT to_jsonb(t)::text FROM orders AS t ORDER BY order_id')).scalars().all()
    digest = hashlib.sha256()
    for row in rows:
        body = row.encode('utf-8')
        digest.update(len(body).to_bytes(8, 'big'))
        digest.update(body)
    return {'rows': len(rows), 'sha256': digest.hexdigest()}

try:
    report['orders_before'] = snapshot()
    with admin.connect() as connection:
        if connection.execute(text('SELECT 1 FROM pg_database WHERE datname=:name'), {'name': name}).first():
            raise RuntimeError('Disposable database unexpectedly exists')
        connection.execute(text('CREATE DATABASE ' + admin.dialect.identifier_preparer.quote(name)))
    report['created'] = True
    environment = dict(os.environ)
    environment['APP_DATA_TEST_DATABASE_URL'] = production.url.set(database=name).render_as_string(hide_password=False)
    environment['PYTHONPATH'] = str(ROOT / 'src')
    environment['PYTHONDONTWRITEBYTECODE'] = '1'
    with (OUT / 'backend-with-postgres.log').open('w', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-p', 'no:cacheprovider',
                                 'src/eval', 'tests', '-q', '-rs', '--disable-warnings'],
                                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
    report['test_exit_code'] = result.returncode
    print('\n'.join((OUT / 'backend-with-postgres.log').read_text(encoding='utf-8').splitlines()[-25:]), flush=True)
finally:
    if report['created']:
        assert re.fullmatch(r'btc_audit_[0-9a-f]{32}', name) and name != production.url.database
        with admin.connect() as connection:
            connection.execute(text('DROP DATABASE ' + admin.dialect.identifier_preparer.quote(name) + ' WITH (FORCE)'))
            report['test_database_removed'] = not bool(connection.execute(
                text('SELECT 1 FROM pg_database WHERE datname=:name'), {'name': name}).first())
    report['orders_after'] = snapshot()
    report['old_orders_unchanged'] = report['orders_before'] == report['orders_after']
    (OUT / 'postgres-tests.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
    production.dispose()
    admin.dispose()
if not report.get('test_database_removed') or not report['old_orders_unchanged']:
    raise RuntimeError('Post-test verification failed')
sys.exit(report.get('test_exit_code', 1))
