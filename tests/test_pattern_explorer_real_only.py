"""Explorer contract: actual local archive only, no synthetic candles/fills."""
import math
from pathlib import Path
import pytest
from wallex_bot.atlas_console import pattern_search


def test_empty_explorer_never_creates_archive(tmp_path):
    r=pattern_search(tmp_path)
    assert r['query'] is None and not r['matches']
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize('changes',[{'symbol':'../secret'},{'resolution':'bad'},{'length':10000},{'k':1000},{'method':'historical_random'},{'scope':'unknown'}])
def test_search_is_bounded_and_allowlisted(tmp_path,changes):
    with pytest.raises(ValueError):pattern_search(tmp_path,**changes)


@pytest.fixture(scope='module')
def actual():
    root=Path('atlas_store')
    if not (root/'catalog.sqlite').exists() or not (root/'research_challengers/milestone8/pattern_index_v1/patterns.sqlite').exists():
        pytest.skip('Genuine archive/index absent; no replacement data')
    r=pattern_search(root,k=4)
    if not r.get('query') or not r['matches']:pytest.skip('Insufficient genuine matches')
    return r


def test_real_comparison_excludes_future_and_has_contiguous_candles(actual):
    q=actual['query'];step=900
    assert len(q['bars'])==q['length']==10
    assert q['end']<=q['decision_time']
    for m in actual['matches']:
        assert m['outcome_end']<=q['start']-step
        assert m['available_at']<=q['decision_time']
        assert m['symbol']==q['symbol']
        bars=m['bars']+m['future_bars']
        assert len(bars)==22
        assert all(b['timestamp']-a['timestamp']==step for a,b in zip(bars,bars[1:]))
        assert m['normalized_close']==pytest.approx([100*b['close']/bars[0]['close'] for b in bars])
        for h in actual['horizons']:
            assert m['outcomes'][str(h)]['close_log_return']==pytest.approx(math.log(m['future_bars'][h-1]['close']/m['bars'][-1]['close']))
    assert [m['distance'] for m in actual['matches']]==sorted(m['distance'] for m in actual['matches'])


def test_real_comparison_never_promotes_or_claims_current_when_stale(actual):
    assert actual['research_only'] and not actual['decision_path_eligible']
    assert actual['archive_only_no_network']
    if actual['query_age_seconds']>1800:assert actual['freshness']=='STALE_ARCHIVE_NOT_CURRENT_MARKET'


def test_browser_uses_on_demand_search_and_real_candle_payload():
    js=Path('wallex_bot/static/console_v2.js').read_text(encoding='utf-8')
    assert '/api/pattern-search?' in js and 'analogueCandles' in js
    assert 'Math.expm1(o.close_log_return)' in js
    assert 'request!==patternRequest' in js
