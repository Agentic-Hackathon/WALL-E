"""Stage 11 tests: structural checks and metadata only, NO market price fixtures."""
import ast
import json
import sqlite3
from pathlib import Path

import pytest
from wallex_bot.atlas_feature_health import feature_health_report, _read_catalog_symbols, _known_denominator_conditions


def test_absent_catalog_does_not_create_files_or_directories(tmp_path):
    root=tmp_path/'not-created'
    report=feature_health_report(root)
    assert report['status']=='NO_EXISTING_CATALOG'
    assert report['mutations'] is False and report['network_requests'] is False
    assert not root.exists()


def test_no_market_history_never_fabricated_from_catalog_metadata(tmp_path):
    db=sqlite3.connect(tmp_path/'catalog.sqlite')
    db.execute('CREATE TABLE assets(symbol TEXT PRIMARY KEY,metadata TEXT NOT NULL,observed_at TEXT NOT NULL)')
    db.execute('INSERT INTO assets VALUES(?,?,?)',('BTCTMN',json.dumps({
       'symbol':'BTCTMN','is_spot':True,'quote_asset':'TMN','quote_volume_24h':500}),
       '2026-10-22T00:00:00Z'))
    db.execute('CREATE TABLE chunks(symbol TEXT,resolution TEXT,status TEXT,begin INTEGER,filename TEXT,sha256 TEXT)')
    db.commit();db.close()
    report=feature_health_report(tmp_path)
    assert report['symbols'][0]['status']=='NO_VERIFIED_15MIN_CANDLES'
    assert report['symbols'][0]['source_sha256_verified'] is True
    assert not (tmp_path/'forward_observations.sqlite').exists()


def test_wrong_mode_and_invalid_identifiers_fail_closed(tmp_path):
    for kw in [{'resolution':'1'}, {'top':0},{'top':25},{'symbol':'../../secret'}]:
        with pytest.raises(ValueError):feature_health_report(tmp_path,**kw)
    assert list(tmp_path.iterdir())==[]


def test_selection_uses_catalog_metadata_only(tmp_path):
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE assets(metadata TEXT)')
    for name,vol,spot,quote in [('BTCTMN',100,True,'TMN'),('ETHUSDT',1000,True,'USDT'),
                                ('ETHTMN',200,True,'TMN'),('DOGE',400,False,'TMN')]:
        db.execute('INSERT INTO assets VALUES(?)',(json.dumps({'symbol':name,'quote_volume_24h':vol,
                                      'is_spot':spot,'quote_asset':quote}),))
    assert _read_catalog_symbols(db,8)==['ETHTMN','BTCTMN']
    db.close()


def test_no_price_imputation_and_no_implicit_trading_dependency():
    module=Path(__file__).parents[1]/'wallex_bot'/'atlas_feature_health.py'
    src=module.read_text('utf8')
    tree=ast.parse(src)
    dependencies=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):dependencies.update(a.name.split('.')[0] for a in node.names)
        if isinstance(node,ast.ImportFrom) and node.module:dependencies.add(node.module.split('.')[0])
    assert not (dependencies & {'requests','torch','wallex_api','atlas_broker','atlas_shadow'})
    assert not any(x in src for x in ('INSERT INTO','UPDATE forecasts','DELETE FROM','WALLEX_API_KEY'))
    assert "market.normalize(frame)" in src
    assert "_hexsha(candidate)!=digest" in src


def test_cli_stays_read_only_early_dispatch():
    src=(Path(__file__).parents[1]/'wallex_bot'/'atlas_cli.py').read_text('utf8')
    assert "args.command=='feature-health'" in src
    assert src.index("args.command=='feature-health'") < src.index('lake=Lake()')
