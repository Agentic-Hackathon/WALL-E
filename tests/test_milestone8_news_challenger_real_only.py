"""Use only actual archived article/candle inputs, no constructed headlines."""
from pathlib import Path
import json
from wallex_bot.atlas_archive import Lake
from wallex_bot.atlas_news_pipeline import NewsStore,MODEL_REVISION
from wallex_bot.atlas_news_challenger import evaluate,ARMS
from wallex_bot.atlas_technical_evidence import technical_registry

ROOT=Path(__file__).resolve().parents[1]

def test_four_news_arms_do_not_impute_missing_pit_data():
    lake=Lake(ROOT/'atlas_store');store=NewsStore(lake.root)
    try:
        result=evaluate(lake,store)
        assert {r['arm'] for r in result['arms']}==set(ARMS) and not result['promotion']
        if result['status']=='INSUFFICIENT_PIT_NEWS_VALIDATION':assert all(r['mae'] is None for r in result['arms'])
    finally:store.close();lake.close()

def test_pinned_finbert_card_not_assumed_permissive_for_contest():
    card=ROOT/'atlas_store/news_models/models--ProsusAI--finbert/snapshots'/MODEL_REVISION/'README.md'
    assert 'license: cc-by-nc-sa-4.0' in card.read_text(encoding='utf-8').lower()

def test_new_technical_definitions_are_versioned_without_champion_change():
    definitions=technical_registry()['definitions']
    assert len(definitions)==15 and any('fibonacci' in r['name'] for r in definitions)
    assert all(r['formula'] and r['availability'] and r['provenance'] and r['warmup_bars']>=1 for r in definitions)
