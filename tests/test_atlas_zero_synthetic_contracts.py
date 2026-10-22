"""Architectural/safety contracts only: zero market observations, fake quotes or mocked fills."""
import sqlite3
from pathlib import Path
import pytest
from wallex_bot.atlas_archive import Lake,ALL_RESOLUTIONS,period_seconds
from wallex_bot.atlas_deep import build_model
from wallex_bot.atlas_news import iso_utc,news_known_at
from wallex_bot.atlas_shadow import PaperAccount
from wallex_bot.atlas_cli import main


def test_complete_interval_catalog_no_fabricated_candles():
    assert {'1','5','15','30','60','180','240','360','480','720','1D','2D','3D'}<=set(ALL_RESOLUTIONS)
    assert period_seconds('15')==900
    assert period_seconds('3D')==3*86400


def test_empty_archive_rejects_unseen_market_data(tmp_path):
    lake=Lake(tmp_path)
    try:
        assert lake.symbols()==[]
        assert lake.status()['candles']==0
        with pytest.raises(ValueError,match='No verified real data'):
            lake.load('BTCTMN','15')
    finally:lake.close()


def test_news_point_in_time_only(tmp_path):
    lake=Lake(tmp_path)
    try:
        assert news_known_at(lake,'2026-10-21T20:00:00+00:00')==[]
        assert iso_utc('20261021T170000Z')=='2026-10-21T17:00:00+00:00'
    finally:lake.close()


def test_paper_memory_is_durable_without_market_fixtures(tmp_path):
    lake=Lake(tmp_path)
    first=PaperAccount(lake)
    assert first.verify()
    with first.db:first.log('SYSTEM','OBSERVATION_ONLY',{'safety':'NO_MARKET_PRICES_PROVIDED'})
    first.close()
    second=PaperAccount(lake)
    try:
        assert second.verify()
        assert second.db.execute('SELECT count(*) FROM events').fetchone()[0]==1
    finally:second.close();lake.close()


def test_transformer_is_real_trainable_nn_not_dummy_signal():
    torch=pytest.importorskip('torch')
    for arch in ('itransformer','patchtst'):
        model=build_model(arch,96,16)
        assert sum(p.numel() for p in model.parameters())>5_000_000
        assert any(p.requires_grad for p in model.parameters())


def test_cli_does_not_expose_live_order_command(capsys):
    with pytest.raises(SystemExit) as ex: main(['--help'])
    assert ex.value.code==0
    text=capsys.readouterr().out
    assert 'archive-all' in text and 'agent-cycle' in text
    assert 'submit-live-orders' not in text
