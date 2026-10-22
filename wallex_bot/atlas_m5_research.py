"""Reproducible research CLI using Atlas verified archives, never execution.

Sources: Atlas M2–M4, original PatchTST/iTransformer implementations unchanged;
independent orchestration. Optional evidence is checked on actual cutoff joins.
"""
from __future__ import annotations
import argparse,csv,json,sqlite3,time,uuid,hashlib
from pathlib import Path
from datetime import datetime,timezone
import numpy as np
from .atlas_m5_data import prepare,freeze,feature_groups,digest,iso,Bundle,SEEDS
from .atlas_m5_models import train,metrics

def save(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def csvsave(path,rows,fields=None):
    fields=fields or list(dict.fromkeys(k for row in rows for k in row)) or ['status']
    with Path(path).open('w',newline='',encoding='utf8') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for row in rows:writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})

def load_bundle(directory):
    directory=Path(directory)
    read=lambda name:json.loads((directory/name).read_text(encoding='utf8'))
    arrays=dict(np.load(directory/'inputs.npz')) if (directory/'inputs.npz').exists() else {}
    return Bundle(read('config.json'),read('samples.json'),arrays,read('split.json'),read('coverage.json'),read('source_manifest.json'))

def optional_eligibility(root,bundle):
    from .atlas_feature_provenance import microstructure_at
    from .atlas_feature_health import _verified_segments
    counts={g:0 for g in 'DEFG'};reasons={};news=None
    # Inspect a SQLite backup: NewsStore's schema initialization must never
    # mutate the operational ledger during a BACKTEST research audit.
    import tempfile
    from .atlas_news_pipeline import NewsStore
    with tempfile.TemporaryDirectory(prefix='atlas_m5_news_') as tmp:
        path=Path(root)/'news.sqlite'
        if path.exists():
            source=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
            dest=sqlite3.connect(str(Path(tmp)/'news.sqlite'));source.backup(dest);source.close();dest.close()
            news=NewsStore(tmp)
        db=sqlite3.connect((Path(root)/'catalog.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
        hourly={s:_verified_segments(Path(root),db,s,'60')[0] for s in {r['symbol'] for r in bundle.rows}}
        try:
            for row in bundle.rows:
                cutoff=row['feature_cutoff'];book=microstructure_at(root,row['symbol'],cutoff)
                bok=book['status']=='VERIFIED_REAL_SNAPSHOT_AT_CUTOFF'
                nok=bool(news and news.features_at(row['symbol'],iso(cutoff))['ready'])
                # The full hourly feature-context warmup must precede cutoff;
                # unknown actual receipt coverage is not silently PIT-approved.
                hok=False
                if row['feature_available_at'] is not None:
                    hok=any(len(p[p.timestamp.astype('int64')+3600<=cutoff])>=151 for p in hourly[row['symbol']])
                counts['D']+=int(hok);counts['E']+=int(bok);counts['F']+=int(nok);counts['G']+=int(bok and nok)
        finally:
            db.close()
            if news:news.close()
    for g in counts:reasons[g]={'eligible_common_rows':counts[g],'status':'INSUFFICIENT_PIT_NEWS_VALIDATION' if g in 'FG' else 'INSUFFICIENT_REAL_OPTIONAL_CONTEXT',
        'missing_mask':True,'missing_reason':feature_groups()[g]['optional_dependency'],
        'training_executed':False,'required_four_way_counts':[256,64,64,64]}
    return reasons

def preflight(root,run,reports):
    run=Path(run);run.mkdir(parents=True,exist_ok=False);reports=Path(reports);reports.mkdir(exist_ok=True)
    coverage=[];bundles=[]
    for res,h in [('15',.75),('60',48),('60',72),('1D',48),('1D',72),('15',48),('15',72)]:
        b=prepare(root,res,h);frozen=freeze(b,run/f'dataset_{res}_{h}')
        coverage.append({'resolution':res,'horizon_hours':h,'common_samples':len(b.rows),'split':b.split,
            'coverage_by_symbol':b.coverage,'frozen':frozen});bundles.append(b)
    b=bundles[0];optional=optional_eligibility(root,b)
    groups=feature_groups()
    for g in 'ABC':groups[g].update(eligible_common_rows=len(b.rows),status=b.split['status'])
    for g in 'DEFG':groups[g].update(optional[g])
    groups['B']['identical_to_A_on_shared_samples']=bool(b.rows and np.array_equal(b.arrays['A'],b.arrays['B']))
    save(reports/'m5_feature_groups.json',groups);save(reports/'m5_dataset_coverage.json',coverage)
    contracts={
        'CLOSE_TO_CLOSE_RETURN':{'formula':'log(close(t+h)/close(t))','execution_price':False,'available':'retrospective verified closed candles only'},
        'MID_TO_MID_RETURN':{'formula':'log(actual_future_mid/actual_mid)','requires':'two hash-verified actual quote receipts at declared times'},
        'ASK_TO_FUTURE_BID_NET_PROXY':{'formula':'future_bid*(1-exit_fee)/(ask*(1+entry_fee))-1','requires':'actual quotes, verified fee; never fills'},
        'POSITIVE_AFTER_COST_OPPORTUNITY':{'formula':'verified net quote proxy > 0','requires':'same real quote and verified cost evidence'},
        'QUANTILE_RETURN_FORECAST':{'formula':'conditional quantiles .1/.5/.9 of declared log-return label','realized_pnl':False}}
    save(reports/'m5_target_contract_audit.json',{'run_directory':str(run),'contracts':contracts,
        'candle_timestamp':'open; close=timestamp+period','decision_time':'closed candle end',
        'receipt_policy':'unknown legacy timestamps remain null; historical availability NOT asserted',
        'feature_available_at':'conservative latest recorded source receipt if entire symbol has receipts; otherwise null',
        'target_observed_at':'same conservative receipt bound, never target candle close relabelled as receipt',
        'evaluation_track':b.config['evaluation_track'],'purge':'target_end < next boundary - one bar; global across symbols',
        'gaps':'split contiguous verified segments; no interpolation','manifest':'SHA256 verified bytes before loading; exact filenames and hashes frozen',
        'source_code_sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('atlas_m5_*.py')},
        'walk_forward_48_72':'INSUFFICIENT_REAL_TRAINING_HISTORY','research_45m':'one fixed retrospective holdout, not repeated walk-forward',
        'multiple_testing':'every arm/seed recorded; correlated time and asset samples not independent; no significance claim'})
    csvsave(reports/'m5_news_ablation.csv',[{'comparison':x,'status':'INSUFFICIENT_PIT_NEWS_VALIDATION','eligible_rows':optional['F']['eligible_common_rows'],'trained':False} for x in ['PRICE_ONLY_vs_PRICE_PLUS_NEWS','PRICE_PLUS_TECHNICAL_vs_PRICE_PLUS_TECHNICAL_NEWS']])
    save(run/'preflight.json',{'coverage':coverage,'groups':groups})
    return b,coverage,groups

def execute(root,run,reports,*,dataset_key='15_0.75'):
    from .atlas_m5_baselines import evaluate
    reports=Path(reports);run=Path(run)
    if (run/'preflight.json').exists():
        b=load_bundle(run/('dataset_'+dataset_key));p=json.loads((run/'preflight.json').read_text(encoding='utf8'));coverage=p['coverage'];groups=p['groups']
    else:b,coverage,groups=preflight(root,run,reports)
    if dataset_key!='15_0.75':b=load_bundle(run/('dataset_'+dataset_key))
    contract={'dataset_key':dataset_key,'dataset_sha256':b.config.get('dataset_sha256'),
        'split_sha256':b.split.get('split_sha256')}
    contract_path=run/'experiment_contract.json'
    if contract_path.exists() and json.loads(contract_path.read_text())!=contract:
        raise ValueError('RUN_DATASET_CONTRACT_MISMATCH_USE_NEW_RUN_DIRECTORY')
    if (run/'results.json').exists():
        old=json.loads((run/'results.json').read_text())
        if any(r['config']['dataset_sha256']!=b.config.get('dataset_sha256') for r in old if 'config' in r):
            raise ValueError('RUN_DATASET_CONTRACT_MISMATCH_USE_NEW_RUN_DIRECTORY')
    if not contract_path.exists():save(contract_path,contract)
    if dataset_key!='15_0.75':
        groups=feature_groups()
        groups.update({g:{**groups[g],**spec} for g,spec in optional_eligibility(root,b).items()})
        for g in 'ABC':groups[g].update(eligible_common_rows=len(b.rows),status=b.split['status'])
        save(reports/'m5_feature_groups.json',groups)
    horizon_hours=b.config['horizon_hours']
    registry=[];results=[];curves=[]
    for item in coverage:
        if f"{item['resolution']}_{item['horizon_hours']}"!=dataset_key:
            for architecture in ('itransformer','patchtst'):
                registry.append({'experiment':f"{architecture}_{item['resolution']}_{item['horizon_hours']}",'status':item['split']['status'],'trained':False})
    for g in 'DEFG':registry.append({'experiment':g,'status':groups[g]['status'],'trained':False})
    if b.split['status']!='ELIGIBLE_RETROSPECTIVE_RESEARCH':
        csvsave(reports/'m5_experiment_registry.csv',registry);raise ValueError('INSUFFICIENT_REAL_TRAINING_HISTORY')
    base_dir=run/'baselines'
    baseline=json.loads((base_dir/'results.json').read_text()) if (base_dir/'results.json').exists() else evaluate(b,base_dir)
    for r in baseline:
        r.update(architecture=r['name'],head='baseline',directory=str(base_dir),horizon_hours=horizon_hours)
        results.append(r);registry.append({'experiment':r['name'],'status':'COMPLETED','trained':True,'seed':r['seed']})
    plan=[(g,a,'ordered',s) for g in 'AC' for a in ('itransformer','patchtst') for s in SEEDS]
    plan += [('A','itransformer',head,s) for head in ('raw','penalty') for s in SEEDS]
    # Registry exists before training. Completed runs are never overwritten;
    # interrupted runs require explicit checkpoint resume with exact provenance.
    for g,a,h,s in plan:registry.append({'experiment':f'{g}_{a}_{h}_{s}','status':'PLANNED','trained':False,'seed':s})
    csvsave(reports/'m5_experiment_registry.csv',registry)
    for g,a,h,s in plan:
        directory=run/f'{g}_{a}_{h}_{s}'
        if (directory/'result.json').exists():r=json.loads((directory/'result.json').read_text())
        else:r=train(b,g,a,h,s,directory,resume=(directory/'resume.pt').exists())
        r.update(name=f'{g}_{a}_{h}_{s}',group=g,architecture=a,head=h,seed=s,horizon_hours=horizon_hours)
        results.append(r)
        for entry in registry:
            if entry['experiment']==r['name']:entry.update(status='COMPLETED',trained=True,checkpoint_sha256=r['checkpoint_sha256'])
        curves.extend({'experiment':r['name'],**x} for x in r['history'])
        save(run/'results.json',results);csvsave(reports/'m5_training_curves.csv',curves);csvsave(reports/'m5_experiment_registry.csv',registry)
    registry.append({'experiment':'B_shared','status':'IDENTICAL_INPUT_REUSE_A_NOT_INDEPENDENT_TRIAL','trained':False})
    csvsave(reports/'m5_experiment_registry.csv',registry)
    csvsave(reports/'m5_training_runs.csv',[{k:v for k,v in r.items() if k not in ('history','validation','test_raw','test_calibrated','calibration')} for r in results if 'epochs' in r])
    comparison=[];calibration=[];symbols=[];y=np.array([row['y'] for row in b.rows]);test=b.split['indices']['test']
    for r in results:
        comparison.append({'experiment':r['name'],'group':r['group'],'architecture':r['architecture'],'head':r['head'],'seed':r['seed'],
            'validation_pinball':r['validation']['pinball'],**r['test_raw'],'calibrated_pinball':r['test_calibrated']['pinball']})
        for kind in ('test_raw','test_calibrated'):calibration.append({'experiment':r['name'],'kind':kind,**r[kind]})
        filename='predictions.npz' if 'epochs' in r else r['name']+'_predictions.npz'
        predictions=np.load(Path(r['directory'])/filename)['test_calibrated']
        for symbol in sorted({b.rows[i]['symbol'] for i in test}):
            positions=[j for j,i in enumerate(test) if b.rows[i]['symbol']==symbol]
            symbols.append({'experiment':r['name'],'symbol':symbol,'horizon_hours':horizon_hours,**metrics(y[np.array(test)[positions]],predictions[positions])})
    csvsave(reports/'m5_model_comparison.csv',comparison);csvsave(reports/'m5_quantile_calibration.csv',calibration);csvsave(reports/'m5_symbol_horizon_results.csv',symbols)
    # Selection uses validation alone, aggregated over all three seeds.
    deep=[r for r in results if 'epochs' in r];keys=sorted({(r['group'],r['architecture'],r['head']) for r in deep})
    aggregate=[]
    for key in keys:
        rr=[r for r in deep if (r['group'],r['architecture'],r['head'])==key]
        aggregate.append({'group':key[0],'architecture':key[1],'head':key[2],'seeds':len(rr),
            'validation_pinball_mean':float(np.mean([r['validation']['pinball'] for r in rr])),
            'test_pinball_mean':float(np.mean([r['test_raw']['pinball'] for r in rr])),
            'test_pinball_seed_std':float(np.std([r['test_raw']['pinball'] for r in rr],ddof=1))})
    aggregate.sort(key=lambda r:r['validation_pinball_mean']);save(reports/'m5_seed_summary.json',aggregate)
    key=aggregate[0];selected=min((r for r in deep if all(r[k]==key[k] for k in ('group','architecture','head'))),key=lambda r:r['validation']['pinball'])
    save(run/'research_selection.json',{'policy':'minimum mean validation pinball across seeds, then minimum validation seed; NOT test selected',
        'selected':selected['name'],'directory':selected['directory'],'checkpoint_sha256':selected['checkpoint_sha256'],'dataset_key':dataset_key,'promotion':False})
    economic={'status':'NO_VERIFIED_ECONOMIC_EDGE','live':'HARD_DISABLED','selected_by_validation':selected['name'],
        'horizons_48_72':'INSUFFICIENT_REAL_TRAINING_HISTORY','fee_verified':False,'executable_pnl':None,
        'gross_return':None,'net_return':None,'max_drawdown':None,'turnover':None,'portfolio_exposure':None,'liquidity_constraints':'insufficient real future book coverage',
        'cash_TMN_return':0,'buy_hold_executable_return':None,'reason':'Close-to-close overlapping research labels are neither trades nor verified fills. No fee or executable spread assumptions are passed off as actual costs.',
        'close_log_return_sensitivity_only':[]}
    pred=np.load(Path(selected['directory'])/'predictions.npz')['test_calibrated']
    for cost in (0,.001,.002,.005,.01):
        economic['close_log_return_sensitivity_only'].append({'hypothetical_round_trip_cost':cost,
            'q10_exceeds_assumed_cost_fraction':float((pred[:,0]>np.log1p(cost)).mean()),
            'actual_positive_label_fraction':float((y[test]>np.log1p(cost)).mean()),'executable':False})
    save(reports/'m5_economic_evaluation.json',economic)
    return run

def main():
    parser=argparse.ArgumentParser(description='Read-only-model M5 research; no orders/promotion')
    parser.add_argument('command',choices=['preflight','run']);parser.add_argument('--root',default='atlas_store')
    parser.add_argument('--reports',default='reports');parser.add_argument('--run-directory')
    parser.add_argument('--dataset-key',choices=['15_0.75','60_48','60_72','1D_48','1D_72','15_48','15_72'],default='15_0.75',
        help='Train this frozen horizon only when its four-way split is eligible; use a separate run directory per dataset')
    args=parser.parse_args();run=Path(args.run_directory) if args.run_directory else Path(args.root)/'research_challengers'/'milestone5'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8])
    if args.command=='preflight':preflight(args.root,run,args.reports)
    else:execute(args.root,run,args.reports,dataset_key=args.dataset_key)
    print(str(run.resolve()))

if __name__=='__main__':main()
