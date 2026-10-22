"""No invented market data or fabricated market returns. Contracts only."""
import ast
from pathlib import Path
from wallex_bot.atlas_edge_triage import edge_triage_report, read_cost_and_timing, read_shadow_errors, classify_recorded_error


def test_empty_location_never_creates_db_or_directories(tmp_path):
    before=list(tmp_path.iterdir())
    result=edge_triage_report(tmp_path)
    assert result['forecast_cost_and_timing']['status']=='NO_EXISTING_FORWARD_LEDGER'
    assert result['shadow_errors']['status']=='NO_EXISTING_SHADOW_LEDGER'
    assert not result['order_submission'] and not result['writes_or_permission_changes']
    assert list(tmp_path.iterdir())==before


def test_missing_subdirectory_no_side_effects(tmp_path):
    root=tmp_path/'does_not_exist'
    assert read_cost_and_timing(root)['status']=='NO_EXISTING_FORWARD_LEDGER'
    assert read_shadow_errors(root)['status']=='NO_EXISTING_SHADOW_LEDGER'
    assert not root.exists()


def test_known_source_error_is_categorized_without_exposing_payload():
    assert classify_recorded_error('RuntimeError: Latest genuine candle is stale; refresh market archive')=='STALE_GENUINE_CANDLE'
    assert classify_recorded_error('RuntimeError: arbitrary message including secrets')=='RUNTIME_ERROR_UNCLASSIFIED_FROM_STORED_EVIDENCE'
    assert classify_recorded_error('ReadTimeout: arbitrary message')=='NETWORK_READTIMEOUT'
    assert classify_recorded_error(None)=='ERROR_NOT_RECORDED'


def test_audit_has_no_http_writes_sql_modifications_or_market_fixtures():
    source=(Path(__file__).parents[1]/'wallex_bot'/'atlas_edge_triage.py').read_text('utf-8')
    tree=ast.parse(source)
    imports=set()
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): imports.update(x.name.split('.')[0] for x in n.names)
        if isinstance(n,ast.ImportFrom) and n.module:imports.add(n.module.split('.')[0])
    assert not imports.intersection({'requests','urllib','socket','http','torch','market','wallex_api'})
    for forbidden in ('INSERT INTO','UPDATE forecasts','DELETE FROM','CREATE TABLE','WALLEX_API_KEY'):
        assert forbidden not in source


def test_cli_registration_is_read_only_early_dispatch():
    src=(Path(__file__).parents[1]/'wallex_bot'/'atlas_cli.py').read_text('utf8')
    assert "args.command=='edge-triage'" in src
    assert src.index("args.command=='edge-triage'")<src.index('lake=Lake()')


def test_forward_median_field_no_longer_uses_mean():
    src=(Path(__file__).parents[1]/'wallex_bot'/'atlas_forward.py').read_text('utf8')
    assert "'median_forecast_mae_log_return':round(float(np.median(abs(actual-predicted)))" in src
    assert "'mean_forecast_mae_log_return':round(float(np.mean(abs(actual-predicted)))" in src
