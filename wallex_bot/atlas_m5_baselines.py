"""Train-only baselines; Atlas decomposition idea, no third-party code copied.

DLinear-ridge is an explicitly scalar-return adaptation, NOT the paper's
multistep SGD implementation. LightGBM uses its installed quantile objective.
"""
from pathlib import Path
import json
import numpy as np
from .atlas_m5_models import QUANT,metrics,fit_calibration,apply_calibration

def evaluate(bundle,directory):
    from sklearn.linear_model import Ridge
    from lightgbm import LGBMRegressor,early_stopping,log_evaluation
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    y=np.array([r['y'] for r in bundle.rows]);ids=bundle.split['indices'];tr=ids['train'];va=ids['validation']
    close=np.array([r['history_close_log'] for r in bundle.rows]);momentum=np.array([r['past_log_return'] for r in bundle.rows])[:,None]
    volatility=np.maximum(np.diff(close,axis=1).std(1),1e-8)
    # Endpoint-padded centred moving average uses only each observed input
    # window. No future observations beyond its feature cutoff are consumed.
    padded=np.pad(close,((0,0),(12,12)),mode='edge')
    trend=np.stack([padded[:,j:j+25].mean(1) for j in range(close.shape[1])],axis=1)
    decomposed=np.concatenate([trend,close-trend],axis=1)
    predictions={}
    for name,point in [('zero',np.zeros(len(y))),('historical_mean',np.full(len(y),y[tr].mean())),
                       ('historical_median',np.full(len(y),np.median(y[tr])))]:
        residual=np.quantile(y[tr]-point[tr],QUANT)
        predictions[name]=point[:,None]+residual
    # A strictly zero forecast, distinct from the residual interval baseline.
    predictions['zero'][:]=0
    for name,X in [('momentum',momentum),('volatility_scaled',momentum/volatility[:,None]),('DLinear_ridge',decomposed)]:
        model=Ridge(alpha=1.0).fit(X[tr],y[tr]);point=model.predict(X)
        predictions[name]=point[:,None]+np.quantile(y[tr]-point[tr],QUANT)
        np.savez_compressed(directory/(name+'.npz'),coef=model.coef_,intercept=model.intercept_)
    X=bundle.arrays['A'][:,-1,:]
    pred=[];best=[]
    for tau in QUANT:
        model=LGBMRegressor(objective='quantile',alpha=float(tau),n_estimators=500,num_leaves=7,
            min_child_samples=25,learning_rate=.03,random_state=17,n_jobs=2,verbosity=-1)
        model.fit(X[tr],y[tr],eval_set=[(X[va],y[va])],callbacks=[early_stopping(25,verbose=False),log_evaluation(0)])
        pred.append(model.predict(X));best.append(model.best_iteration_)
        model.booster_.save_model(str(directory/f'lightgbm_q{tau}.txt'))
    predictions['LightGBM_quantile']=np.stack(pred,axis=1)
    results=[]
    for name,pred in predictions.items():
        calibration=fit_calibration(y[ids['calibration']],pred[ids['calibration']],bundle.rows,bundle.split)
        calibrated=apply_calibration(pred[ids['test']],calibration)
        item={'name':name,'group':'A','seed':17,'validation':metrics(y[va],pred[va]),
              'test_raw':metrics(y[ids['test']],pred[ids['test']]),'test_calibrated':metrics(y[ids['test']],calibrated),
              'calibration':calibration,'best_iterations':best if name=='LightGBM_quantile' else None}
        results.append(item)
        np.savez_compressed(directory/(name+'_predictions.npz'),test_raw=pred[ids['test']],test_calibrated=calibrated)
    (directory/'results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    return results
