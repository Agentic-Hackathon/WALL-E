"""Contract tests: no synthetic OHLCV, fake API payloads, or invented prices."""
from pathlib import Path
import pytest
from wallex_bot.cli import main
from wallex_bot.segmented_eval import load_catalog_segments


def test_gap_mode_is_explicit_and_visible(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['fetch-history','--help'])
    assert exc.value.code == 0
    assert '--allow-gaps' in capsys.readouterr().out


def test_segment_evaluation_is_explicit(capsys):
    with pytest.raises(SystemExit) as exc:
        main(['segment-eval','--help'])
    assert exc.value.code == 0
    content = capsys.readouterr().out
    assert '--catalog' in content and '--hours' in content


def test_segment_evaluation_cannot_run_without_genuine_catalog(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_catalog_segments(str(tmp_path/'nonexistent_real_data.segments.json'), 'BTCTMN', '15')


def test_no_price_generator_reintroduced():
    from wallex_bot import cli, research_data, segmented_eval
    folder=Path(cli.__file__).resolve().parent.parent
    assert not (folder/'examples'/'synthetic.csv').exists()
    assert not (folder/'wallex_bot'/'fixtures.py').exists()
    assert 'make-fixture' not in Path(cli.__file__).read_text(encoding='utf8')
    assert 'No fabricated candles' in Path(research_data.__file__).read_text(encoding='utf8')
    assert 'never across missing OHLCV' in Path(segmented_eval.__file__).read_text(encoding='utf8')
