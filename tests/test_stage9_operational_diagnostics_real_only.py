"""Stage 9: operational audit contracts use NO synthetic market data or simulated quotes."""
import ast
from pathlib import Path
from wallex_bot.atlas_operational import operational_report,watch_audit,shadow_audit,forward_audit,news_audit


def test_empty_archive_is_observational_only(tmp_path):
    before=list(tmp_path.iterdir())
    out=operational_report(tmp_path)
    assert out['mode']=='OPERATIONS_READ_ONLY_EXISTING_EVIDENCE'
    assert out['forward']['status']=='NO_FORWARD_DATABASE'
    assert out['shadow']['status']=='NO_SHADOW_DATABASE'
    assert out['watch']['status']=='NO_WATCH_LOG'
    assert out['news']['status']=='NO_NEWS_DATABASE'
    assert list(tmp_path.iterdir())==before


def test_missing_paths_do_not_create_directories(tmp_path):
    nested=tmp_path/'nonexistent_path'
    assert not nested.exists()
    assert operational_report(nested)['database_mutation'] is False
    assert not nested.exists()


def test_no_market_api_or_order_submission_code():
    source=(Path(__file__).parents[1]/'wallex_bot'/'atlas_operational.py').read_text(encoding='utf8')
    tree=ast.parse(source)
    modules=set()
    for node in ast.walk(tree):
        if isinstance(node,ast.Import): modules.update(n.name.split('.')[0] for n in node.names)
        elif isinstance(node,ast.ImportFrom) and node.module:modules.add(node.module.split('.')[0])
    assert not ({'requests','socket','urllib','http','wallex_api','market','torch'}&modules)
    assert 'INSERT INTO' not in source and 'UPDATE ' not in source and 'DELETE FROM' not in source


def test_all_independent_observers_empty(tmp_path):
    assert shadow_audit(tmp_path)['status']=='NO_SHADOW_DATABASE'
    assert forward_audit(tmp_path)['status']=='NO_FORWARD_DATABASE'
    assert news_audit(tmp_path)['status']=='NO_NEWS_DATABASE'
    assert watch_audit(tmp_path)['status']=='NO_WATCH_LOG'
