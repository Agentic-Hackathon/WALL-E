"""Stage 12 safety/structure tests — NO fake OHLCV or market fixtures."""
import ast
import sqlite3
from pathlib import Path
import pytest
from wallex_bot.atlas_feature_recipe import feature_recipe_report, POLICY, CONTEXT, MIN_BARS


def test_absent_archive_is_read_only_and_creates_nothing(tmp_path):
    root=tmp_path/'not_created'
    result=feature_recipe_report(root)
    assert result['status']=='NO_EXISTING_ARCHIVE'
    assert result['symbols']==[]
    assert result['no_network_no_orders_no_db_writes'] is True
    assert result['champion_riskgate_watch_unchanged'] is True
    assert not root.exists()


def test_metadata_only_archive_has_no_invented_market_data(tmp_path):
    db=sqlite3.connect(tmp_path/'catalog.sqlite')
    db.execute('CREATE TABLE assets(metadata TEXT)')
    db.execute('INSERT INTO assets VALUES(?)',('{"symbol":"USDTTMN","is_spot":true,"quote_asset":"TMN","quote_volume_24h":300}',))
    db.execute('CREATE TABLE chunks(symbol TEXT,resolution TEXT,status TEXT,begin INTEGER,filename TEXT,sha256 TEXT)')
    db.commit();db.close()
    result=feature_recipe_report(tmp_path)
    assert result['symbols'][0]['status']=='NO_VERIFIED_GENUINE_CANDLES'
    assert result['no_network_no_orders_no_db_writes'] is True
    assert not (tmp_path/'forward_observations.sqlite').exists()


def test_input_restrictions_fail_closed(tmp_path):
    for kwargs in ({'resolution':'60'}, {'top':0}, {'top':25}, {'symbol':'../../danger'}):
        with pytest.raises(ValueError):feature_recipe_report(tmp_path,**kwargs)
    assert list(tmp_path.iterdir())==[]


def test_new_command_precedes_lake_construction():
    source=(Path(__file__).parents[1]/'wallex_bot'/'atlas_cli.py').read_text('utf8')
    assert source.index("args.command=='feature-recipe-audit'")<source.index('lake=Lake()')


def test_recipe_is_not_imported_into_execution_or_training():
    root=Path(__file__).parents[1]/'wallex_bot'
    for file in ('atlas_deep.py','atlas_signals.py','atlas_shadow.py','atlas_watch.py',
                 'atlas_risk.py','atlas_broker.py','atlas_agent.py'):
        assert 'atlas_feature_recipe' not in (root/file).read_text('utf8')
    src=(root/'atlas_feature_recipe.py').read_text('utf8')
    nodes=ast.walk(ast.parse(src))
    imports=[]
    for node in nodes:
        if isinstance(node,ast.Import):imports.extend(a.name for a in node.names)
        if isinstance(node,ast.ImportFrom):imports.append(node.module or '')
    assert not any('requests' in i or 'wallex_api' in i or 'torch' in i for i in imports)
    assert not any(x in src for x in ('INSERT INTO','DELETE FROM','UPDATE forecasts','WALLEX_API_KEY'))
    assert CONTEXT==96 and MIN_BARS==151
    assert 'EXPERIMENTAL' in POLICY


def test_repeated_execution_without_archive_does_not_create_evidence(tmp_path):
    path=tmp_path/'archive'
    a=feature_recipe_report(path);b=feature_recipe_report(path)
    assert a==b
    assert not path.exists()
