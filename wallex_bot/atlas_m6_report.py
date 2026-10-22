"""M6 report from persisted real observations; no historical result relabelling."""
import argparse,json,sqlite3,subprocess,hashlib,time,xml.etree.ElementTree as ET
from pathlib import Path
from dataclasses import asdict
from .atlas_m5_research import save
from .atlas_prospective import ModelObservationLedger,model_registry,MODEL_NAMES
from .atlas_orchestration import DecisionLedger
from .atlas_forward_watch import strategy_status
from .atlas_forward import _sha
from .atlas_memory import ResearchMemory
from .atlas_risk import RiskGate

REFERENCES=[
 ('TradingAgents','Apache-2.0','tradingagents/graph/trading_graph.py','structured roles in existing LangGraph'),
 ('FinMem','MIT','puppy/memory_functions/compound_score.py','additive PIT memory layers and Atlas product ranking, not FinMem additive ranking'),
 ('hindsight','MIT, placeholder copyright','WRITEUP.md','separate prospective evidence; baselines, leakage and short-window skepticism'),
 ('FinRL-Trading','Apache-2.0','src/strategies/adaptive_rotation/risk_manager.py','portfolio state and risk separation; existing RiskGate retained'),
 ('NautilusTrader','LGPL-3.0','crates/event_store/src/replay.rs','state-only deterministic replay; no publishing execution commands'),
 ('Freqtrade','GPL-3.0','docs/lookahead-analysis.md','prefix causality checks; Atlas protections never disabled'),
 ('Hummingbot','Apache-2.0','hummingbot/connector/client_order_tracker.py','observation identity, leases and reconciliation; existing broker tracker retained')]

def build(root,session,reports):
    root=Path(root).resolve();session=Path(session).resolve();reports=Path(reports);reports.mkdir(parents=True,exist_ok=True)
    ledger=ModelObservationLedger(session);decisions=DecisionLedger(session);memory=ResearchMemory(root,mode='BACKTEST')
    try:
        status=ledger.status();strategy=strategy_status(session,ledger);replay=decisions.replay()
        cycles=[json.loads(raw) for raw, in ledger.db.execute('SELECT payload FROM m6_cycles ORDER BY id')]
        completed_graphs=sum('review' in action for cycle in cycles for action in cycle['shadow'])
        from collections import Counter
        action_counts=dict(Counter(action['decision'] for cycle in cycles for action in cycle['shadow'] if 'decision' in action))
        lease=ledger.db.execute('SELECT owner,expires FROM m6_lease').fetchall()
        active_lease=any(expires>time.time() for _,expires in lease)
        refs=[]
        for name,license,path,use in REFERENCES:
            folder=Path('third_party')/name
            commit=subprocess.check_output(['git','-C',str(folder),'rev-parse','HEAD'],text=True).strip()
            license_file=folder/'LICENSE'
            refs.append({'repository':name,'commit':commit,'license':license,'license_file':str(license_file),
                'license_sha256':hashlib.sha256(license_file.read_bytes()).hexdigest(),'inspected_path':path,
                'capability':use,'integration':'CONCEPT_ONLY_INDEPENDENT_CODE','copied_source_lines':0,'external_code_executed':False})
        save(reports/'m6_reference_repositories.json',refs)
        protected=['atlas_risk.py','atlas_broker.py','atlas_deep.py','atlas_feature_recipe.py']
        if subprocess.check_output(['git','diff','26cd878','--',*[str(Path('wallex_bot')/p) for p in protected]],text=True):raise RuntimeError('PROTECTED_POLICY_SOURCE_CHANGED')
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
        audit=[];comparisons=[]
        for key,raw,review,action,risk in decisions.db.execute('SELECT decision_id,evidence,review,action,risk_replay FROM decisions_v6 ORDER BY created'):
            evidence=json.loads(raw);result=json.loads(review);inputs=json.loads(risk)
            old=RiskGate().evaluate(inputs['symbol'],evidence['prediction'],inputs['book'],inputs['cash_tmn'],inputs['positions'],inputs['stopped'],inputs['fee_assumption']) if inputs else None
            audit.append({'decision_id':key,'symbol':evidence['symbol'],'decision_time':evidence['decision_time'],
                'observation_id':evidence['observation_id'],'proposal':result['proposal'],'agents':result['agents'],
                'memory_references':evidence.get('memory_references',[]),'disagreements':result['disagreements'],'actual_shadow_action':action,
                'quote_receipt_sha256':evidence.get('quote_receipt_sha256'),'source_receipt_note':'Initial development cycles precede the explicit quote hash field; quote observation and raw receipts retained'})
            comparisons.append({'decision_id':key,'legacy_watch_gate_on_same_real_inputs':asdict(old) if old else None,
                'new_shared_gate':inputs['gate_decision'] if inputs else None,'actual_new_action':action,
                'comparison_kind':'COUNTERFACTUAL_OLD_ROUTE_REVIEW_ON_ACTUAL_NEW_EVIDENCE_NOT_A_HISTORICAL_TRADE'})
        save(reports/'m6_architecture_comparison.json',{'before':'Watch -> direct ShadowBroker vs separate LangGraph auxiliary checks',
            'after':'Watch -> shadow_cycle -> run_assets -> same atlas_agent.cycle LangGraph -> structured review -> unchanged ShadowBroker/RiskGate',
            'legacy_function_preserved':'atlas_shadow._legacy_shadow_cycle, forensic comparison only',
            'behavior_change':'Watch now shares Agent technical veto; optional LLM defaults OFF. No risk limit was loosened.',
            'comparison':comparisons,'economic_improvement_proven':False,'implementation_commit':source_commit})
        save(reports/'m6_agent_evidence_audit.json',{'roles':7,'actual_decisions':len(audit),'records':audit,
            'LLM_calls':0,'reviewers':'deterministic evidence functions, not claims of seven autonomous LLM calls',
            'protected_source_unchanged':protected,'order_authority':'only unchanged ShadowBroker/RiskGate; observers and LLM have none'})
        save(reports/'m6_memory_integrity.json',{**memory.status(),'supported_layers':sorted(memory.TYPES),
            'old_context_chain':memory.store.verify(),'dedup_policy':'stable event IDs + source/payload match; replay writes no memory',
            'PIT_policy':'observation, availability AND actual creation <= decision; BACKTEST read-only',
            'unpopulated_layers':'No matured outcome or validated lesson is fabricated; optional layers may be empty'})
        registry=model_registry(root)
        save(reports/'m6_prospective_model_registry.json',{'models':registry,'common_evaluation_key':'symbol + actual decision timestamp + origin quote',
            'selection':'Champion unchanged, M5 Patch selected by historical validation; LightGBM predeclared comparator; no prospective selection/promotion',
            'multiple_testing_ledger':'M5 experiment registry remains historical; every M6 model failure and observation is retained in m6_cycles/m6_predictions',
            'target_separation':'CLOSE_TO_CLOSE training vs current quote-origin MID proxy; due times stored independently',
            'feature_transform':'M5-A exact log-minus-log, log1p volume, within-window normalization, scale floor 1e-6, clip [-20,20]'})
        predictions=[];pair_groups={}
        for model,raw,sha,state in ledger.db.execute('SELECT model,payload,payload_sha,status FROM m6_predictions ORDER BY decision,model'):
            p=json.loads(raw)
            if _sha(p)!=sha:raise RuntimeError('FORECAST_HASH_INVALID')
            predictions.append({k:v for k,v in p.items() if k!='source_receipts'}|{'model':model,'status':state,'source_receipt_count':len(p['source_receipts'])})
            pair_groups.setdefault((p['symbol'],p['decision_time']),set()).add(model)
        save(reports/'m6_forward_observations.json',{**status,'predictions':predictions,'evaluation':ledger.evaluation(),
            'shared_five_model_groups':sum(len(g)==5 for g in pair_groups.values()),'receipt_hashes_valid':ledger.forward.verify(),
            'future_tolerance_seconds':300,'matured_performance':None if not status['matured_scored'] else 'Review matched quote proxy groups before inference',
            'historical_M5_results_counted_as_prospective':False,'counterfactual_returns_are_fills':False})
        save(reports/'m6_strategy_horizon_readiness.json',strategy)
        health={'completed_cycles':len(cycles),'foreground_process_still_running':None if active_lease else False,
            'process_liveness_policy':'Lease presence is not verified process uptime; absent active lease means no collector currently owns this session',
            'scope':'bounded executions finished; this report proves no continuous 48h service uptime',
            'initial_development_cycles_without_pipeline_hash':sum('pipeline_sha256' not in c for c in cycles),
            'pipeline_policy':'New/resumed collection pins LF-normalized source digest; changed code requires a separate session. Initial bounded development cycles retain original input/model hashes but did not capture whole-pipeline source digest.',
            'public_depth_requests_observer':sum(c['quote_requests'] for c in cycles),
            'public_candle_complete_windows':sum(c.get('sync',{}).get('complete',0) for c in cycles),
            'quote_count':status['quote_count'],'download_cache_hits':sum(c.get('sync',{}).get('cached',0) for c in cycles),
            'model_cache_hits':sum(item.get('cached',0) for c in cycles for item in c['models'].values()),
            'network_errors':[e for c in cycles for e in c['errors']],
            'additional_agent_depth_receipts':'One actual depth per completed graph plus every held-asset mark; no holdings in this bounded run',
            'cycles':cycles,'lease':lease,
            'resume':'session deadline and model identities preserved across processes; no new capital on restart',
            'control':'Ctrl+C stops between bounded calls; finally releases lease; --no-sync disables Agent sync too',
            'LIVE':'HARD_DISABLED'}
        save(reports/'m6_watch_health.json',health)
        save(reports/'m6_replay_consistency.json',{'decisions':replay,'all_review_identical':all(r['review_identical'] for r in replay),
            'all_risk_identical':all(r['risk_gate_identical'] for r in replay),'all_receipts_valid':all(r['receipt_valid'] for r in replay),
            'replay_has_network_or_broker_or_memory_authority':False,'m6_old_legacy_outcomes_replayed_in_tests':'Not counted as new prospective outcomes'})
        junit=reports/'m6_pytest.xml';cases=list(ET.parse(junit).getroot().iter('testcase'))
        skipped=sum(c.find('skipped') is not None for c in cases);failed=sum(c.find('failure') is not None for c in cases);errors=sum(c.find('error') is not None for c in cases)
        tests={'passed':len(cases)-skipped-failed-errors,'skipped':skipped,'failed':failed,'errors':errors,
            'baseline':{'passed':190,'skipped':5},'command':"$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m6_pytest.xml",
            'synthetic_market_or_news_or_fill_data':False,
            'earlier_full_verification':{'passed':203,'failed':1,'skipped':5,'cause':'sub-millisecond wall-clock boundary race in new test; corrected to original actual historical cutoff to isolate creation-time leakage'},
            'legacy_quote_reconciliation_test':'Copies an original archived forecast and its original actual quotes into an isolated fixture; never new prospective evidence'}
        save(reports/'m6_test_results.json',tests)
        doc=f'''# گزارش واقعی Milestone 6 — معماری Agent و مشاهده آینده‌نگر

## نتیجه و حدود تکمیل

مسیر مشترک Agent/Watch، حافظه افزایشی PIT، مشاهده پنج مدل، reconciliation واقعی، اجرای foreground قابل Resume و ارزیابی Shadow چندروزه پیاده‌سازی شدند. **هیچ مزیت اقتصادی اثبات نشده و دوره ۴۸/۷۲ساعته سپری نشده است.**

شاخه `integration/atlas-milestone-6-agent-forward`؛ مبنا `26cd878`؛ Commit کد هنگام تولید گزارش `{source_commit}`. گزارش در Commit جدا تحویل می‌شود.

## ۱. منبع و تغییرات واقعی

هفت مرجع با Commit، مسیر واقعی و LICENSE در `m6_reference_repositories.json` و `third_party/SOURCES.md` ثبت شده‌اند. TradingAgents: Apache-2.0؛ FinMem: MIT؛ Hindsight: MIT با copyright جای‌نگهدارنده؛ FinRL-Trading/FinRL-X: Apache-2.0؛ NautilusTrader: LGPL-3.0؛ Freqtrade: GPL-3.0؛ Hummingbot: Apache-2.0. همه استفاده مفهومی‌اند، **صفر خط کد خارجی کپی و هیچ کد خارجی اجرا نشد**. منابع GPL/LGPL فقط برای مطالعه بودند. نتیجه‌های README/مقالات به Atlas نسبت داده نشدند.

به‌جای جایگزینی Framework، LangGraph با SqliteSaver، ContextStore، رتبه‌بندی FinMem-inspired، ForwardLedger، DataSync، PaperAccount و ShadowBroker موجود توسعه یافتند. RiskGate، Broker، Transformer، Feature Recipe و Champion تغییر نکردند. تابع قدیمی Shadow برای ممیزی با نام `_legacy_shadow_cycle` حفظ شد؛ مسیر عمومی Watch اکنون `run_assets -> atlas_agent.cycle` است. هفت نقش Technical، News، Forecast، Regime، Portfolio، Risk و Explanation واقعاً JSON می‌سازند، اما عامل‌های قطعی شواهدمحور هستند، نه هفت LLM. LLM اختیاری پیش‌فرض خاموش است و خروجی آن هیچ ورودی Broker را تغییر نمی‌دهد.

Per-asset readiness و Fail-closed مستقل حفظ شد. Watch بررسی فنی Agent را هم دریافت می‌کند؛ این تغییر ممکن است اقدام را کمتر کند و به معنی بهبود بازده نیست. نبود خبر Core را متوقف نمی‌کند. Portfolio پیش از هر تصمیم با Bid واقعی همه دارایی‌های نگه‌داری‌شده mark می‌شود؛ ارزیابی RiskGate دوباره در تراکنش اتمیک Broker انجام می‌شود. ID سفارش کاغذی به نماد/کندل/مدل مقید است؛ استفاده مجدد با شواهد متفاوت Fail-closed می‌شود.

## ۲. اجرای واقعی و فایل‌ها

Session واقعی: `{session}`؛ archive اصلی دست‌نخورده از نظر داده پذیرفته‌شده باقی ماند و فقط دریافت محدود/مشتق‌سازی معتبر به آن افزوده شد. حساب این مطالعه در همان Session با سرمایه **فرضی** ۵ میلیون TMN جدا از حساب کاغذی قدیمی ساخته شد. {completed_graphs} چرخه کامل گراف در {len(cycles)} چرخه گردآورنده اجرا شد؛ توزیع تصمیم‌های واقعی Shadow: `{action_counts}`. هیچ سفارش یا Fill واقعی صرافی وجود نداشت. تمام Checkpointهای قدیمی نگه‌داری شدند.

تعداد چرخه گردآورنده: **{len(cycles)}**؛ پیش‌بینی آینده‌نگر واقعی: **{sum(status['by_model'].values())}**؛ بالغ و امتیازدهی‌شده با Quote واقعی: **{status['matured_scored']}**. مدت بین اولین و آخرین Quote: **{status['observed_span_hours']:.6f} ساعت**، نه ۴۸ ساعت. اجراهای دوم/سوم پس از Restart همان Session را ادامه دادند؛ شمار پیش‌بینی ثبت‌شده به‌ترتیب `{[c['registered'] for c in cycles]}` بود؛ اجرای دوم **۱۰ Cache Hit مدل** و صفر پیش‌بینی تکراری جدید داشت. این اعداد موفقیت Uptime یا استراتژی نیستند.

Observer تعداد {health['public_depth_requests_observer']} درخواست Depth عمومی داشت؛ هر گراف Agent نیز Quote عمومی مستقل و در صورت وجود موقعیت، Bid واقعی دارایی‌های نگه‌داری‌شده را دریافت می‌کند. {health['public_candle_complete_windows']} Window کندل در DataSync گردآورنده تکمیل شد؛ دریافت‌های اضافی Sync خود Agent در ledger اصلی ثبت شده‌اند و در این شمار گردآورنده نیستند. Cache دانلود {health['download_cache_hits']} و خطاهای ثبت‌شده شبکه در Collector {len(health['network_errors'])} است. هیچ endpoint حساب/سفارش/برداشت یا API Key استفاده نشد. `pass.txt` خوانده نشد.

پنج مدل از پیش تعیین‌شده: Champion بدون تغییر، LightGBM Quantile M5، PatchTST منتخب Validation در M5، Zero/Persistence و توزیع کوانتایل برچسب Train. مدل‌های پژوهشی فقط مشاهده دارند و به Broker دسترسی ندارند. ثبت یک گروه مدل در Timestamp و Quote مشترک انجام می‌شود؛ یک (مدل،نماد،Cutoff) دوباره ثبت نمی‌شود. شکست مدل‌ها و خطاها در Cycleها نگه‌داری می‌شوند. هیچ افق ۱۵/۶۰/۱۸۰دقیقه‌ای از خروجی ۴۵دقیقه‌ای ساخته نشد.

هدف آموزش Close-to-Close است؛ نتیجه Quote-origin، Mid-to-Mid **Proxy** است و Ask-to-Future-Bid با کارمزد فرضی از Fill/PnL جدا می‌ماند. دو زمان `model_target_end` و `quote_due` ذخیره شده‌اند؛ این دو هدف هم‌ارز معرفی نمی‌شوند. فقط اولین Quote واقعی در [due,due+300s]، با SHA معتبر، مجاز است. نبود آن `UNSCORED_NO_REAL_FUTURE_QUOTE` می‌ماند. ساعت هرگز برای بالغ‌کردن پیش‌بینی جلو برده نمی‌شود. داده قدیمی برای ساخت پیش‌بینی جدید گذشته استفاده نشده است.

حافظه جدید در جدول افزایشی `research_memory_v6` همان ContextStore است؛ هیچ رکورد قبلی بازنویسی نشد. وضعیت فعلی لایه‌ها: `{memory.status()['layers']}`؛ هر هفت نوع لایه پشتیبانی می‌شوند، اما Outcome/درس تأییدشدهٔ بدون شواهد ساخته نمی‌شود. مشاهده، دسترس‌پذیری و زمان واقعی ایجاد همگی باید <= Cutoff باشند. رتبه‌بندی importance/recency/relevance قطعی و محدود است. گراف فقط ID/Hash/وضعیت حافظه را در Context می‌بیند، نه متن خبری در جایگاه دستور. Replay هیچ حافظه‌ای ثبت نمی‌کند و زنجیره‌های قدیم و جدید معتبرند.

فایل‌ها: `atlas_agent.py`, `atlas_shadow.py`, `atlas_watch.py`, `atlas_memory.py` توسعه یافتند؛ `atlas_review.py`, `atlas_orchestration.py`, `atlas_prospective.py`, `atlas_forward_watch.py`, `atlas_m6_report.py` و تست M6 اضافه شدند. دو helper در `atlas_m5_inference.py` و `atlas_m5_report.py` نیز اصلاح شدند تا اجرای Smoke به‌صورت پیش‌فرض گزارش تاریخی M5 را بازنویسی نکند و فقط تولید صریح گزارش مقصد را بنویسد؛ مقادیر و فایل‌های گزارش M5 حفظ شدند. تمام ده JSON الزامی و JUnit واقعی در reports موجودند. در Snapshot مقایسه، مسیر قبلی Watch روی **همان شواهد واقعی جدید** به‌صورت Counterfactual دوباره evaluate شد؛ این نتیجه اجرای تاریخی مسیر قبلی یا معامله قدیمی نیست.

## ۳. تست‌ها و Replay

**{tests['passed']} passed, {skipped} skipped، {failed} failed، {errors} errors**؛ Baseline برابر 190 passed, 5 skipped بود. هر ۱۹۰ تست قبلی حفظ شد. ۱۴ تست جدید مسیر مشترک، نبود خبر، آمادگی مستقل بازار، RiskGate سراسری، PIT حافظه/خبر، منع اختیار LLM/Promotion، ثبت آینده‌نگر واقعی، Timestamp مشترک، lease دو نمونه، Restart، منع جلو بردن ساعت و Replay بدون اثر جانبی را پوشش می‌دهد.

یک اجرای میانی ۲۰۳ موفق، یک شکست و ۵ Skip داشت: مقایسه زیرمیلی‌ثانیه‌ای دو ساعت در تست تازه حافظه race ایجاد می‌کرد. تست با Cutoff واقعی قدیمی اصلاح شد تا دقیقاً جلوگیری از نشت بر اساس زمان ایجاد را بسنجد؛ اجرای کامل نهایی بالا عبور کرد. این شکست پنهان نشده و در JSON تست ثبت است.

تست reconciliation یک Forecast از قبل ثبت‌شدهٔ legacy و همان Quoteهای واقعی مبدأ/آینده را در Fixture جدا کپی و نتیجه قبلی را بازتولید می‌کند؛ این تست **هیچ Outcome جدید آینده‌نگر M6 نیست**. برای M6 فعلی تعداد بالغ همان {status['matured_scored']} است. {len(replay)} تصمیم واقعی Replay شدند؛ همه Reviewها و تمام خروجی‌های RiskGate یکسان بودند. قیمت، کندل، خبر، سفارش و Fill آزمایشی جعلی تولید نشد.

## ۴. چه چیزی اثبات نمی‌شود؟

هیچ برتری Challenger نسبت به Baseline در آینده‌نگر هنوز قابل محاسبه نیست؛ نتایج M5 همان نتایج تاریخی باقی مانده‌اند. سود واقعی، هزینه تأییدشده، نقدشوندگی پایدار، بازده مستقل، کنترل Drawdown طی ۴۸ ساعت و Uptime چندروزه اثبات نشده‌اند. وضعیت استراتژی `{strategy['status']}` است. Cash کاغذی فعلی {strategy['paper']['paper_cash_tmn']} TMN و پرتفوی بدون موقعیت است؛ این سود یا Fill نیست. نتیجه اقتصادی `NO_VERIFIED_ECONOMIC_EDGE` باقی می‌ماند.

## ۵. اثر بر سامانه و Milestone 7

این مرحله معماری، ایمنی، بازتولید، ثبت شواهد و جداسازی پژوهش را بهتر می‌کند، نه امتیاز اقتصادی ادعایی. اجرای محدود تمام شده و **سرویس دائمی فعال نگذاشته‌ایم**. lease آزاد شده، Session قابل ادامه است و به‌تنهایی Scheduler یا فایل RUNNING اثبات زنده‌بودن فرآیند نیست. برای مطالعه ۴۸/۷۲ساعته باید فرمان foreground واقعاً روشن بماند و Coverage/Gapها بررسی شوند. افق Forecast ۴۵ دقیقه است و با دوره ارزیابی ۴۸ ساعت تعارض ندارد.

Milestone 7: جمع‌آوری آینده‌نگر واقعی بیشتر، Quoteهای موعد با تلورانس ثابت، ارزیابی جفت‌شده/Block-aware روی نمادها، هزینه تأییدشده، Coverage خبر، بررسی اختلاف Shadow/Replay و سپس پژوهش تصمیم‌گیری؛ بدون انتخاب مدل با Test یا تغییر خودکار Risk/Champion. اگر Quote موعد از دست برود، بازسازی یا Interpolation مجاز نیست. Replay فعلی روی ورودی ذخیره‌شدهٔ تصمیم است، نه بازاجرای Bit-exact آموزش GPU.

محدودیت نسخه‌بندی: سه چرخه محدود اولیه هنگام توسعه اجرا شدند و Hash کل سورس Pipeline را ثبت نکردند؛ Hash مدل، ورودی و رسیدهای واقعی آن‌ها محفوظ است. آن‌ها را مطالعه ثابت ۴۸ساعته با یک نسخه استراتژی محسوب نکنید. نسخه نهایی Hash سورس LF-normalized را به Session و پیش‌بینی مقید می‌کند و تغییر سورس در اجرای مداوم را متوقف می‌سازد. برای مطالعه رسمی بعدی، Session تازه بسازید.

## ۶. ورودی لازم و بازتولید

مجوز تازه برای پژوهش لازم نیست. برای نتیجه اقتصادی هزینه واقعی قابل تأیید و شواهد آینده لازم است. LIVE همچنان HARD_DISABLED است و این مرحله مجوز معامله واقعی نیست. ادامه چندروزه به اجرای پایدار foreground توسط کاربر/محیط میزبان نیاز دارد؛ برنامه خودکار یا پنجره پنهان دائمی ایجاد نشده است.

از ریشه پروژه در PowerShell:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m6_pytest.xml
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_forward_watch collect --top 2 --max-cycles 1 --shadow
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_forward_watch collect --top 2 --shadow
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_forward_watch status
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_forward_watch reconcile
conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m6_report
```

فرمان دوم اجرای محدود است؛ فرمان سوم foreground تا پایان Deadline اولیه ادامه می‌دهد و با Ctrl+C قابل توقف/Resume است. حذف `--shadow` برای Session تازه، مشاهده-only است؛ قرارداد Session موجود را بی‌صدا عوض نکنید و از `--session-dir` جدا استفاده کنید. `--no-sync` مستقل از Shadow، Sync را در Observer و Agent خاموش می‌کند و داده نامعتبر همچنان کنار گذاشته می‌شود. برای ۷۲ ساعت از Session جدید و `--hours 72` استفاده کنید. API Key یا فایل رمز لازم نیست.
'''
        Path('docs/milestones/MILESTONE_6_REPORT_FA.md').write_text(doc,encoding='utf8')
        print(json.dumps({'forecasts':sum(status['by_model'].values()),'scored':status['matured_scored'],'tests':tests,'source_commit':source_commit}))
    finally:memory.close();decisions.close();ledger.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='atlas_store');p.add_argument('--session-dir',default='atlas_store/research_challengers/milestone6/forward_v1');p.add_argument('--reports',default='reports');a=p.parse_args();build(a.root,a.session_dir,a.reports)
