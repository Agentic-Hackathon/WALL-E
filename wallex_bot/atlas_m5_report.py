"""Render M5 evidence from actual saved runs/JUnit; no computed trading PnL.

Source: independently authored on Atlas's actual research artifacts. Statistical
resampling operates on paired loss blocks, never on fabricated market candles.
"""
import argparse,csv,hashlib,json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
from .atlas_m5_research import csvsave,save,load_bundle
from .atlas_m5_models import QUANT
from .atlas_m5_inference import smoke,ProspectiveLedger

def build(run,reports='reports'):
    run=Path(run);reports=Path(reports);results=json.loads((run/'results.json').read_text())
    selection=json.loads((run/'research_selection.json').read_text());coverage=json.loads((reports/'m5_dataset_coverage.json').read_text())
    summary=json.loads((reports/'m5_seed_summary.json').read_text());b=load_bundle(run/'dataset_15_0.75')
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    source={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('wallex_bot').glob('atlas_m5_*.py')}
    audit=json.loads((reports/'m5_target_contract_audit.json').read_text())
    audit.update(delivery_source_sha256=source,implementation_commit=head,
        input_transform_audit={'core_prices':'log relative to last observed close inside each input window','volume':'log1p actual volume',
            'normalization':'mean/std of input window only; scale floor 1e-6; final clip [-20,20]',
            'label':'natural log return, not arithmetic executable return'},
        universe_selection_warning='Top-8 ranked by current observed catalog turnover, not a PIT historical universe; selection/survivorship bias possible',
        code_evolution='Initial source hashes retained separately; resume acceptance added after the primary run; all model input matrices are independently hashed')
    save(reports/'m5_target_contract_audit.json',audit)
    registry=list(csv.DictReader((reports/'m5_experiment_registry.csv').open(encoding='utf8')))
    known={r['experiment'] for r in registry}
    for directory in sorted(run.parent.glob('pilot_*')):
        if str(directory) in known:continue
        files=list(directory.rglob('result.json'))
        registry.append({'experiment':str(directory),'status':'EXPLORATORY_COMPLETED_DUPLICATE_NOT_INDEPENDENT' if files else 'FAILED_CONFIGURATION_CASE_SENSITIVE_ARCHITECTURE',
            'trained':bool(files),'seed':17,'checkpoint_sha256':json.loads(files[0].read_text())['checkpoint_sha256'] if files else ''})
    if (run/'resume_acceptance/result.json').exists() and 'resume_acceptance' not in known:
        rr=json.loads((run/'resume_acceptance/result.json').read_text())
        registry.append({'experiment':'resume_acceptance','status':'REAL_EPOCH_1_PAUSE_RESUME_COMPLETED_DUPLICATE','trained':True,'seed':17,'checkpoint_sha256':rr['checkpoint_sha256']})
        reference=next(r for r in results if r['name']=='A_itransformer_ordered_17')
        save(reports/'m5_resume_acceptance.json',{'directory':str(run/'resume_acceptance'),'paused_after_epoch':1,
            'resumed_through_epoch':rr['epochs'],'best_epoch':rr['best_epoch'],'early_stopping_epoch':rr['early_stopping_epoch'],
            'validation_curve_max_abs_difference':float(max(abs(x['validation_loss']-y['validation_loss']) for x,y in zip(rr['history'],reference['history']))),
            'best_checkpoint_restored':rr['restored_best_checkpoint'],'reference_directory':reference['directory']})
    csvsave(reports/'m5_experiment_registry.csv',registry)
    # Paired time-block aggregation pools simultaneous assets first, then uses
    # nonoverlapping horizon-sized time bins. Bootstrap is descriptive: few
    # blocks + many arms do not support a corrected significance claim.
    y=np.array([b.rows[i]['y'] for i in b.split['indices']['test']]);times=np.array([b.rows[i]['feature_cutoff'] for i in b.split['indices']['test']])
    model=np.load(Path(selection['directory'])/'predictions.npz')['test_raw']
    baseline=np.load(run/'baselines/LightGBM_quantile_predictions.npz')['test_raw']
    loss=lambda p:np.maximum(QUANT*(y[:,None]-p),(QUANT-1)*(y[:,None]-p)).mean(1)
    difference=loss(model)-loss(baseline);bins=(times-times.min())//2700
    values=np.array([difference[bins==k].mean() for k in np.unique(bins)])
    rng=np.random.default_rng(17);boot=rng.choice(values,(2000,len(values)),replace=True).mean(1)
    save(reports/'m5_paired_block_comparison.json',{'comparison':'validation-selected PatchTST seed vs LightGBM quantile',
        'positive_difference_favors':'LightGBM','sample_pairs':len(y),'time_blocks':len(values),'block_seconds':2700,
        'mean_paired_loss_difference':float(difference.mean()),'equal_block_mean_difference':float(values.mean()),
        'descriptive_block_bootstrap_95_interval':np.quantile(boot,[.025,.975]).tolist(),
        'independent_sample_claim':False,'corrected_significance_claim':False,
        'warning':'Very few overlapping-horizon time blocks; market dependence, multiple comparisons and historical universe selection prevent a robust superiority claim'})
    junit=reports/'m5_pytest.xml'
    if junit.exists():
        suites=ET.parse(junit).getroot();cases=list(suites.iter('testcase'))
        skips=sum(c.find('skipped') is not None for c in cases);failures=sum(c.find('failure') is not None for c in cases);errors=sum(c.find('error') is not None for c in cases)
        tests={'passed':len(cases)-skips-failures-errors,'skipped':skips,'failed':failures,'errors':errors,
            'baseline':{'passed':174,'skipped':5},'junit':str(junit),'command':"$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'; conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m5_pytest.xml",
            'plugin_autoload_disabled':True,'synthetic_market_data':False}
        save(reports/'m5_test_results.json',tests)
    else:raise ValueError('ACTUAL_JUNIT_REPORT_REQUIRED')
    smoke_result=smoke('atlas_store',run);ledger=ProspectiveLedger(run/'prospective.sqlite')
    try:save(reports/'m5_forward_status.json',{'status':ledger.status(),'reconciliation':ledger.reconcile('atlas_store'),
        'reason':'No eligible trained 48/72-hour prospective model; no predictions/outcomes fabricated'})
    finally:ledger.close()
    protected=['wallex_bot/atlas_deep.py','wallex_bot/atlas_risk.py','wallex_bot/atlas_broker.py','wallex_bot/atlas_shadow.py','wallex_bot/atlas_agent.py','wallex_bot/atlas_data_sync.py','wallex_bot/atlas_feature_recipe.py']
    changes=subprocess.check_output(['git','diff','905047a','--',*protected],text=True)
    if changes:raise RuntimeError('PROTECTED_SOURCE_CHANGED')
    save(reports/'m5_integrity.json',{'base':'905047a','implementation_commit':head,'protected_files':protected,
        'protected_source_diff_empty':True,'champion_manifest_unchanged_during_smoke':smoke_result['champion_manifest_unchanged'],
        'operational_stores_unchanged_during_smoke':smoke_result['operational_stores_unchanged'],
        'LIVE':'HARD_DISABLED','automatic_promotion':False,'source_sha256':source})
    # Immutable artifacts are checksum-listed separately from the evolving
    # prospective ledger. No old model/dataset/checkpoint is rewritten.
    files=[p for p in run.rglob('*') if p.is_file() and p.suffix not in ('.sqlite','.sqlite-wal','.sqlite-shm')]
    save(reports/'m5_artifact_manifest.json',{'run_directory':str(run.resolve()),
        'files':[{'relative_path':str(p.relative_to(run)),'bytes':p.stat().st_size,
                  'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]})
    deep=[r for r in results if 'epochs' in r];selected=next(r for r in deep if r['name']==selection['selected'])
    lines=['# گزارش واقعی Milestone 5 — Wallex Atlas','',
        '## نتیجه و حدود تکمیل','',
        'کد پژوهش، آموزش واجد شرایط، Calibration مستقل، Resume و Replay پیاده‌سازی و اجرا شدند. هدف اصلی ۴۸/۷۲ ساعت هنوز از نظر داده قابل آموزش نیست؛ این مرحله به معنی اثبات پیش‌بینی بلندمدت یا مزیت اقتصادی نیست. نتیجه: `NO_VERIFIED_ECONOMIC_EDGE`.',
        '',f'شاخه: `integration/atlas-milestone-5-deep-forecasting`؛ مبنا: `905047a`؛ Commit پیاده‌سازی هنگام تولید گزارش: `{head}`. Commit تحویل گزارش جدا ثبت می‌شود.',
        '',f'مسیر نسخه‌دار واقعی: `{run.resolve()}`. هیچ Checkpoint قدیمی، حافظه، داده یا حسابی پاک یا جایگزین نشد. وزن‌ها/دیتاست‌ها در Git نیستند و باید همراه این مسیر نگه‌داری شوند.',
        '', '## ۱. منبع، لایسنس و پیاده‌سازی','',
        'خواندن archive و SHA، DataSyncManager، V1/V2/V3، دو Backbone موجود، BACKTEST memory و NewsStore بازاستفاده شدند. هیچ کد Champion، RiskGate، Broker یا Watch تغییر نکرد. پیاده‌سازی چهار Split، آموزش، Head مرتب، Calibration، ارزیابی و گزارش مستقل نوشته شد.',
        '', 'مرجع DLinear: `cure-lab/LTSF-Linear`، commit `0c113668a3b88c4c4ee586b8c5ec3e539c4de5a6`، Apache-2.0؛ LICENSE و `models/DLinear.py` بررسی شدند. کدی کپی نشد. `DLinear_ridge` تطبیق مستقل trend/residual با میانگین متحرک ۲۵نقطه‌ای، هدف scalar log-return و Ridge است؛ بازتولید آموزش SGD/پیش‌بینی چندگامی مقاله نیست. جزئیات در `third_party/SOURCES.md`.',
        '', '## ۲. داده، فایل‌ها و اجرای واقعی','',
        'چهار Chunk واقعی 60m از API عمومی، با DataSync موجود، Retry صفر، Cache Hit صفر و خطای صفر دریافت شد؛ هفت Window برنامه‌ریزی‌شده در سقف محدود این اجرا باقی ماند. درخواست احرازهویت‌شده یا سفارش وجود نداشت. ریز شواهد در `m5_data_sync.json`.',
        '', '| تایم‌فریم | افق ساعت | نمونه مشترک | وضعیت |','|---|---:|---:|---|']
    for c in coverage:lines.append(f"| {c['resolution']} | {c['horizon_hours']} | {c['common_samples']} | {c['split']['status']} |")
    lines+=['', 'در هیچ‌یک از هشت بازار منتخب، افق ۴۸/۷۲ ساعت با Context و Warmup لازم قابل آموزش نبود؛ بنابراین Walk-forward این افق‌ها اجرا نشد. طول قطعه ساعتی حداکثر ۸۰ بار و روزانه فقط چند بار است. دانلود بلندمدت غیرضروری انجام نشد.',
        '', f"۴۵دقیقه: {len(b.rows)} نمونه واقعی مشترک؛ Splitها: `{b.split['counts']}`؛ {b.split['purged_samples']} نمونه Purge شد. Embargo یک کندل ۹۰۰ثانیه‌ای؛ مرزها از زمان‌ها و نه بازده ساخته شدند. هفت بازار مشترک: PEPE/BTC/PUMP/ETH/USOON/BNB/DOGE با کوت TMN؛ USDT پنجره V1 مشترک معتبر نداشت.",
        '', 'تمام قیمت‌ها از فایل‌های SHA-تأییدشدهٔ واقعی‌اند؛ Gapها به قطعات جدا تقسیم شدند. زمان Candle زمان بازشدن است و Cutoff پایان کندل. برچسب log(close_future/close_now) است، نه بازده قابل اجرای Bid/Ask. Legacy receipt نامعلوم، null باقی مانده و زمان مشاهده با زمان بسته‌شدن جعل نشده است. آزمون فعلی retrospective است، نه PIT آینده‌نگر. انتخاب Universe با Turnover فعلی، سوگیری انتخاب تاریخی بالقوه دارد.',
        '', 'گروه A: پنج ستون OHLCV تبدیل‌شده + ۱۶ ویژگی V1؛ B: همان Core + V2؛ C: چهار ویژگی منتخب `ema50_ratio,hma20_ratio,bb_width20,trend_persistence20` اضافه شد (جمع ۲۵). روی مجموعه مشترک A/B دقیقاً یکسان‌اند و B آموزش تکراری مستقل ندارد. D: صفر پنجره ساعتی PIT واجد شرایط؛ E: فقط ۸۳ نمونه Book مشترک؛ F/G: صفر نمونه خبری PIT. فقدان اختیاری Core را متوقف نکرد و با صفر جعلی پر نشد. این اجرا ادعای انتخاب بهینه از هر ۵۲ ویژگی ندارد.',
        '', 'ماژول‌ها: `atlas_m5_data.py`، `atlas_m5_models.py`، `atlas_m5_baselines.py`، `atlas_m5_research.py`، `atlas_m5_inference.py`، `atlas_m5_report.py`؛ تست: `test_milestone5_research_real_only.py`. تمام خروجی‌های الزامی در reports تولید شده‌اند.',
        '', '## آموزش و نتایج','',
        f"۱۸ آموزش اصلی، {sum(r['epochs'] for r in deep)} Epoch واقعی، Seedهای 17/29/43؛ RTX 4080 SUPER، BF16، AdamW، ReduceLROnPlateau، Clip=1، سقف ۱۲۰ Epoch، Patience=15 و min_delta=1e-5. همه به Early Stopping رسیدند؛ بهترین Epoch اغلب ۱ تا ۴ بود: نشانه کمبود داده/Overfitting، نه توجیه ادامه مصنوعی تا ۱۲۰. مجموع زمان آموزش اصلی {sum(r['elapsed_seconds'] for r in deep):.1f} ثانیه است؛ اندازه نمونه کوچک است.",
        '', '| آزمایش | Epoch توقف | بهترین Epoch | GPU peak MiB |','|---|---:|---:|---:|']
    for r in deep:lines.append(f"| {r['name']} | {r['epochs']} | {r['best_epoch']} | {r['gpu_peak_bytes']/2**20:.1f} |")
    lines+=['', '| گروه/مدل/Head | میانگین Pinball تست | انحراف معیار Seed |','|---|---:|---:|']
    for r in summary:lines.append(f"| {r['group']}/{r['architecture']}/{r['head']} | {r['test_pinball_mean']:.8f} | {r['test_pinball_seed_std']:.8f} |")
    lines+=['', '| Baseline | Pinball تست خام | Pinball پس از Calibration |','|---|---:|---:|']
    for r in results:
        if 'epochs' not in r:lines.append(f"| {r['name']} | {r['test_raw']['pinball']:.8f} | {r['test_calibrated']['pinball']:.8f} |")
    lines+=['',f"انتخاب پژوهشی فقط با میانگین Validation و سپس بهترین Seed همان بازو: `{selected['name']}`، Checkpoint SHA `{selected['checkpoint_sha256']}`؛ بهترین Epoch {selected['best_epoch']}. این انتخاب هیچ Promotion ایجاد نکرد. Pinball خام آن {selected['test_raw']['pinball']:.8f} و پس از Calibration {selected['test_calibrated']['pinball']:.8f} است.",
        '', 'میانگین PatchTST-A از LightGBM خام بهتر نیست؛ افزودن V3 نیز بهبود پایدار نشان نداد. iTransformer در Seed 43 بسیار ناپایدار بود. بنابراین هیچ پیچیدگی تازه‌ای وارد تصمیم عملیاتی نشد. مقایسه جفت‌شده روی بلوک زمانی و همه نتایج نمادها ثبت شده، ولی با تعداد بلوک کم و تعدد مقایسه‌ها ادعای معناداری آماری نمی‌کنیم.',
        '', f"Head مرتب Crossing را به صفر رساند؛ Penalty به‌تنهایی تضمین نکرد. برای مدل منتخب پس از Calibration: پوشش پایین q10={selected['test_calibrated']['q10_lower_coverage']:.4f}، پوشش بالای q90={selected['test_calibrated']['q90_upper_coverage']:.4f}، پوشش بازه={selected['test_calibrated']['interval_coverage']:.4f} در برابر هدف ۰٫۸، عرض={selected['test_calibrated']['interval_width']:.6f} و خطای Calibration={selected['test_calibrated']['calibration_error']:.6f}. کالیبراسیون Pinball را بدتر کرد؛ مرتب بودن معادل کالیبراسیون صحیح نیست. ۷۷ نمونه Calibration هم‌بسته، شواهد بلندمدت کافی نیست.",
        '', 'اخبار: `INSUFFICIENT_PIT_NEWS_VALIDATION`؛ هیچ برتری News گزارش نمی‌شود و محدودیت FinBERT CC-BY-NC-SA-4.0 پابرجاست. Smoke واقعی LangGraph، حافظه BACKTEST، خبر در Cutoff واقعی و Replay را به هم وصل کرد؛ این گراف پژوهشی جداست، نه اجرای گراف معاملاتی SHADOW. هیچ LLM خارجی یا Broker فراخوانی نشد و Hash منطقی News/Memory/Shadow قبل و بعد برابر بود.',
        '', 'Forward ledger فقط در research_challengers است؛ Forecast گذشته را رد می‌کند، ورودی ۴۸/۷۲ واقعی آینده‌نگر می‌خواهد و reconciliation فقط Quote واقعی hash-تأییدشده را جفت می‌کند. اکنون صفر رکورد/Outcome دارد؛ گذشت ۴۸/۷۲ ساعت ادعا نشده است. بازده Mid، Fill یا PnL نیست و هزینه تأییدنشده null می‌ماند.',
        '', '## ۳. تست‌ها','',f"اجرای کامل: **{tests['passed']} passed, {tests['skipped']} skipped، {tests['failed']} failed، {tests['errors']} errors**؛ Baseline: 174 passed, 5 skipped. هیچ تست قدیمی حذف نشد. JUnit واقعی و JSON نتایج نگه‌داری شدند.",
        '', '۱۶ تست جدید شامل Split/Purge، عدم نگاه به آینده روی Prefix واقعی، SHA Manifest، عدم Imputation، ترتیب کوانتایل، جداسازی Calibration، رفتار Early Stopping، بازیابی وزن بهترین Epoch، قطع واقعی پس از Epoch ۱ و Resume، سه Seed واقعی، منع Promotion، ممنوعیت اختلاط Dataset در Run و ایزولاسیون Smoke است. Resume بازوی A/iTransformer/17 منحنی Validation اجرای بدون قطع را با تلورانس ثبت‌شده بازتولید کرد. آزمایش‌های Pilot، یک شکست نام‌گذاری معماری و Resume در Registry جدا ثبت شده‌اند تا تعداد تلاش‌ها پنهان نماند.',
        '', '## ۴. این تغییر چه چیزی را اثبات نمی‌کند؟','',
        'سودآوری، مزیت بعد از کارمزد واقعی، بازده قابل اجرا، Drawdown/Turnover سبد، اعتبار Live، عملکرد ۴۸/۷۲ ساعت، برتری آماری مدل عمیق، اثر خبر یا بازتولید مقاله DLinear اثبات نشده‌اند. هزینه واقعی/Book آینده کافی نیست؛ PnL و Drawdown ساختگی محاسبه نشده و حساسیت q10 صرفاً بر هزینه فرضی روی برچسب Close گزارش شده است. Cash/TMN صفر تعریف حسابداری است، نه نتیجه معامله؛ Buy-and-Hold قابل اجرا بدون شواهد کافی null است.',
        '', '## ۵. اثر بر سامانه و موارد باز','',
        'قابلیت ممیزی، بازتولید، اعتبارسنجی زمانی، کنترل Quantile و خطایابی مدل بهتر شده است؛ امتیاز عددی بارم یا بهبود اقتصادی ادعا نمی‌شود. Sourceهای محافظت‌شده با مبنای 905047a بدون Diff هستند. موارد باز: جمع‌آوری پیوسته واقعی برای Context+Label+Split افق بلند، Receipt کامل PIT، دفتر سفارش هم‌زمان، کارمزد تأییدشده و Walk-forward چندرژیمی. Core و مدل‌های قبلی مستقل باقی مانده‌اند.',
        '', '## ۶. ورودی لازم از کاربر','',
        'برای ادامه پژوهش Core تأیید تازه لازم نیست؛ زمان واقعی و داده بیشتر لازم است. برای ادعای اقتصادی، جدول کارمزد قابل تأیید و دفتر سفارش آینده لازم است. این درخواست هیچ مجوز LIVE نمی‌دهد؛ پکیج/بازار/هزینه و مجوز صریح اجرای واقعی همچنان لازم‌اند.',
        '', '## فرمان‌های بازتولید (از ریشه پروژه، PowerShell)','', '```powershell',
        "$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'",
        'conda run --no-capture-output -n shbk python -m pytest -q --junitxml=reports/m5_pytest.xml',
        'conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_research run',
        'conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_research run --dataset-key 60_48 --reports reports/m5_48h',
        f'conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_research run --run-directory {run}',
        f'conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_inference replay --run-directory {run}',
        f'conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_inference forward-reconcile --run-directory {run}',
        f'conda run --no-capture-output -n shbk python -m wallex_bot.atlas_m5_report --run-directory {run}',
        '```','', 'فرمان بدون run-directory پوشه تازه می‌سازد؛ دادهٔ جاری ممکن است تغییر کرده باشد. فرمان روی پوشه منجمد، نتایج تکمیل‌شده را بازاستفاده می‌کند و آموزش ناقص را فقط با Provenance یکسان Resume می‌کند. اجرای اولیه تست Resume یک آزمایش واقعی جدا می‌سازد؛ تکرارها شواهد تکمیل‌شده را بررسی می‌کنند.']
    path=Path('docs/milestones/MILESTONE_5_REPORT_FA.md');path.parent.mkdir(parents=True,exist_ok=True);path.write_text('\n'.join(lines)+'\n',encoding='utf8')
    print(json.dumps({'tests':tests,'report':str(path),'source_commit':head},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-directory',required=True);p.add_argument('--reports',default='reports');a=p.parse_args();build(a.run_directory,a.reports)
