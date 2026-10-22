"""Progressive, deterministic disclosure of Wallex research skills and tool menus.

These are instructions/metadata, not a plugin that can dynamically execute arbitrary tools.
Untrusted market/news content cannot add a tool or elevate its permission level.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib

SKILLS_ROOT=Path(__file__).resolve().parent.parent/'atlas_skills'

@dataclass(frozen=True)
class Tool:
    name:str
    group:str
    description:str
    permission:str='READ_ONLY'

# Actual operations are implemented in the existing verified modules.
# The registry never uses eval/importlib or external text to resolve a tool.
TOOLS=(
    Tool('market_catalog','market','Read Wallex public spot catalog'),
    Tool('historical_candles','market','Read verified persisted OHLCV segments'),
    Tool('real_order_book','market','Read real Wallex public bids/asks'),
    Tool('technical_indicators','technical','Compute indicators on genuine continuous candles'),
    Tool('model_inference','forecast','Run SHA256-pinned validated forecasting checkpoint'),
    Tool('news_receipts','news','Read articles with first-observed timestamps'),
    Tool('paper_ledger','shadow','Record hypothetical fills using real observed quote','PAPER_ONLY'),
    Tool('forward_receipts','shadow','Score forecasts from later real quotes'),
    Tool('risk_veto','risk','Enforce trade and exposure vetoes'),
    Tool('audit_replay','audit','Read append-only decisions and model provenance'),
)

# Small stable menu always visible. Individual skill text is loaded on demand.
SKILLS={
    'market_data':('market','Real OHLCV, depth, no fabricated quotes'),
    'technical':('technical','Indicator menu; no lookahead'),
    'forecast':('forecast','Model validation, calibration, version provenance'),
    'news':('news','Point-in-time news as quarantined data'),
    'risk':('risk','Spot/TMN safety, portfolio and liquidity vetoes'),
    'shadow':('shadow','Only hypothetical fills on actual observed quotes'),
    'audit':('audit','Hash verification, reproducibility, memory review'),
}
PHASE_SKILLS={
    'watch':('market_data','forecast','risk','shadow','audit'),
    'agent-cycle':('market_data','technical','forecast','news','risk','shadow','audit'),
    'research':('market_data','technical','forecast','news','audit'),
    'audit':('audit',),
}
PHASE_TOOLS={
    'watch':('historical_candles','real_order_book','model_inference','risk_veto','paper_ledger','forward_receipts','audit_replay'),
    'agent-cycle':('historical_candles','real_order_book','technical_indicators','model_inference','news_receipts','risk_veto','paper_ledger','audit_replay'),
    'research':('market_catalog','historical_candles','technical_indicators','news_receipts','model_inference','audit_replay'),
    'audit':('audit_replay',),
}


def menu():
    return [{'name':name,'group':group,'when_to_load':desc} for name,(group,desc) in SKILLS.items()]


def tools_for(phase):
    if phase not in PHASE_TOOLS:raise ValueError('Unrecognized trusted phase')
    return [dict(name=t.name,group=t.group,description=t.description,permission=t.permission)
            for t in TOOLS if t.name in PHASE_TOOLS[phase]]


def skill_index(phase):
    if phase not in PHASE_SKILLS:raise ValueError('Unrecognized trusted phase')
    return [{'name':n,'description':SKILLS[n][1]} for n in PHASE_SKILLS[phase]]


def load_skill(name):
    if name not in SKILLS:raise ValueError('Unregistered skill: '+str(name)[:50])
    p=SKILLS_ROOT/name/'SKILL.md'
    if not p.is_file():raise FileNotFoundError('Missing packaged skill '+name)
    raw=p.read_text(encoding='utf8')
    if len(raw)>5200:raise ValueError('Skill exceeds safe per-skill context budget')
    return {'name':name,'text':raw,'sha256':hashlib.sha256(raw.encode()).hexdigest(),
            'source':'PACKAGE_CONTROLLED_LOCAL_SKILL_NOT_MARKET_CONTENT'}


def skills_for(phase, names=None):
    allowed=set(PHASE_SKILLS[phase]);selection=tuple(names) if names is not None else PHASE_SKILLS[phase]
    if any(n not in allowed for n in selection):raise ValueError('Skill not authorized in phase')
    return [load_skill(n) for n in selection]
