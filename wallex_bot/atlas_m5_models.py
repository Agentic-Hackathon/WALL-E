"""M5 research quantiles, real early stopping, best restore and explicit resume.

Reuses existing Atlas PatchTST/iTransformer backbones unchanged. Ordered head
uses median +/- softplus distances. DLinear decomposition is independently
adapted from cure-lab/LTSF-Linear's documented trend/residual idea (Apache-2.0),
with ridge fitting for a scalar log-return target; no third-party code copied.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
import hashlib,json,time
from pathlib import Path
import numpy as np
from .atlas_m5_data import digest,SEEDS

QUANT=np.array([.1,.5,.9])

@dataclass
class EarlyStop:
    patience:int=15
    min_delta:float=.00001
    best:float=float('inf')
    best_epoch:int=0
    wait:int=0
    def observe(self,loss,epoch):
        if not np.isfinite(loss):raise ValueError('NONFINITE_VALIDATION_LOSS')
        improved=loss<self.best-self.min_delta
        if improved:self.best=float(loss);self.best_epoch=int(epoch);self.wait=0
        else:self.wait+=1
        return improved,self.wait>=self.patience

def ordered_logits(logits):
    import torch
    center=logits[:,1]
    return torch.stack([center-torch.nn.functional.softplus(logits[:,0]),center,
                        center+torch.nn.functional.softplus(logits[:,2])],dim=1)

def metrics(y,prediction):
    y=np.asarray(y,dtype=float);p=np.asarray(prediction,dtype=float)
    if not len(y):return {'n':0}
    if p.shape!=(len(y),3) or not np.isfinite(p).all() or not np.isfinite(y).all():raise ValueError('NONFINITE_FORECAST_OR_LABEL')
    residual=y[:,None]-p;cdf=(y[:,None]<=p).mean(0)
    return {'n':len(y),'pinball':float(np.maximum(QUANT*residual,(QUANT-1)*residual).mean()),
        'q50_mae':float(abs(y-p[:,1]).mean()),'directional_accuracy':float(((p[:,1]>0)==(y>0)).mean()),
        'crossing_rate':float(((p[:,0]>p[:,1])|(p[:,1]>p[:,2])).mean()),
        'q10_lower_coverage':float((y>=p[:,0]).mean()),'q10_cdf':float(cdf[0]),'q90_upper_coverage':float(cdf[2]),
        'interval_width':float((p[:,2]-p[:,0]).mean()),'interval_coverage':float(((y>=p[:,0])&(y<=p[:,2])).mean()),
        'calibration_error':float(abs(cdf-QUANT).mean())}

def fit_calibration(y,prediction,rows,split):
    cal=split['indices']['calibration'];test=split['indices']['test']
    if len(y)!=len(cal) or not cal:raise ValueError('CALIBRATION_SAMPLE_COUNT_MISMATCH')
    if np.asarray(prediction).shape!=(len(cal),3) or not np.isfinite(prediction).all() or not np.isfinite(y).all():raise ValueError('NONFINITE_CALIBRATION')
    if set(cal)&(set(split['indices']['train'])|set(split['indices']['validation'])|set(test)):
        raise ValueError('CALIBRATION_SPLIT_LEAKAGE')
    if cal and test and max(rows[i]['target_end'] for i in cal)>=min(rows[i]['feature_cutoff'] for i in test):raise ValueError('CALIBRATION_TARGET_OVERLAPS_TEST')
    offsets=np.array([np.quantile(np.asarray(y)-prediction[:,i],tau) for i,tau in enumerate(QUANT)])
    return {'version':'INDEPENDENT_RESIDUAL_QUANTILE_SHIFT_REARRANGEMENT_V1','offsets':offsets.tolist(),
            'calibration_ids_sha256':digest([rows[i]['sample_id'] for i in cal]),'samples':len(cal),
            'warning':'Small correlated calibration set; ordered output does not prove coverage'}

def apply_calibration(prediction,calibration):return np.sort(np.asarray(prediction)+np.array(calibration['offsets']),axis=1)

def make_model(architecture,context,channels,head,device):
    import torch
    from .atlas_deep import build_model
    if head not in ('raw','penalty','ordered'):raise ValueError('invalid quantile head')
    class ResearchQuantileModel(torch.nn.Module):
        def __init__(self):
            super().__init__();self.backbone=build_model(architecture,context,channels,device)
        def forward(self,x):
            logits=self.backbone(x)
            return ordered_logits(logits) if head=='ordered' else logits
    return ResearchQuantileModel().to(device)

def _sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def train(bundle,group,architecture,head,seed,directory,*,max_epochs=120,resume=False,batch_size=16,pause_after_epoch=None):
    import torch
    if bundle.split['status']!='ELIGIBLE_RETROSPECTIVE_RESEARCH':raise ValueError('INSUFFICIENT_REAL_TRAINING_HISTORY')
    if seed not in SEEDS or not 1<=max_epochs<=120 or batch_size<1:raise ValueError('invalid research training configuration')
    directory=Path(directory)
    if not resume:directory.mkdir(parents=True,exist_ok=False)
    elif not (directory/'resume.pt').is_file():raise ValueError('EXPLICIT_RESUME_CHECKPOINT_REQUIRED')
    torch.manual_seed(seed);np.random.seed(seed)
    if torch.cuda.is_available():torch.cuda.manual_seed_all(seed)
    device='cuda' if torch.cuda.is_available() else 'cpu';torch.set_num_threads(4)
    X=bundle.arrays[group];y=np.array([r['y'] for r in bundle.rows],dtype='float32')
    ids=bundle.split['indices'];mu=float(y[ids['train']].mean());sd=max(float(y[ids['train']].std()),1e-6)
    scaled=(y-mu)/sd;model=make_model(architecture,X.shape[1],X.shape[2],head,device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=3e-4,weight_decay=1e-3)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,mode='min',factor=.5,patience=5)
    stopper=EarlyStop();rng=np.random.default_rng(seed);history=[];epoch_start=1;total_started=time.monotonic()
    config={'architecture':architecture,'group':group,'head':head,'seed':seed,'context':X.shape[1],'channels':X.shape[2],
        'target_mean':mu,'target_scale':sd,'dataset_sha256':bundle.config['dataset_sha256'],
        'source_manifest_sha256':bundle.config['source_manifest_sha256'],'split_sha256':bundle.split['split_sha256'],
        'feature_input_sha256':hashlib.sha256(X.tobytes()).hexdigest(),'max_epochs':max_epochs,
        'patience':15,'min_delta':.00001,'batch_size':batch_size,'training_device':device,
        'mixed_precision':device=='cuda','no_automatic_promotion':True}
    if resume:
        saved=torch.load(directory/'resume.pt',map_location=device,weights_only=True)
        if saved['config']!=config:raise ValueError('RESUME_PROVENANCE_OR_CONFIGURATION_MISMATCH')
        model.load_state_dict(saved['model']);optimizer.load_state_dict(saved['optimizer']);scheduler.load_state_dict(saved['scheduler'])
        stopper=EarlyStop(**saved['stopper']);history=saved['history'];epoch_start=saved['epoch']+1
        torch.set_rng_state(saved['torch_rng'].cpu());rng.bit_generator.state=saved['numpy_rng']
        if device=='cuda':torch.cuda.set_rng_state(saved['cuda_rng'].cpu())
        batch_size=history[-1]['batch_size_actual'] if history else batch_size
    quant=torch.tensor([.1,.5,.9],device=device)
    def loss_fn(pred,true):
        error=true[:,None]-pred;loss=torch.maximum(quant*error,(quant-1)*error).mean()
        return loss+.05*torch.relu(pred[:,:2]-pred[:,1:]).mean() if head=='penalty' else loss
    def epoch_pass(indices,training):
        nonlocal batch_size
        model.train(training);chosen=rng.permutation(indices) if training else np.asarray(indices);losses=[];norms=[];pos=0
        while pos<len(chosen):
            selection=chosen[pos:pos+batch_size]
            try:
                xx=torch.from_numpy(X[selection]).to(device);yy=torch.from_numpy(scaled[selection]).to(device)
                with torch.set_grad_enabled(training),torch.autocast(device_type=device,dtype=torch.bfloat16,enabled=device=='cuda'):
                    pred=model(xx);loss=loss_fn(pred,yy)
                if not torch.isfinite(loss):raise ValueError('NONFINITE_TRAINING_LOSS')
                if training:
                    optimizer.zero_grad(set_to_none=True);loss.backward();norm=torch.nn.utils.clip_grad_norm_(model.parameters(),1.0)
                    optimizer.step();norms.append(float(norm))
                losses.append(float(loss.detach().cpu())*len(selection));pos+=len(selection)
            except torch.OutOfMemoryError:
                optimizer.zero_grad(set_to_none=True)
                if batch_size<=1:raise
                batch_size=max(1,batch_size//2);torch.cuda.empty_cache()
        return sum(losses)/len(chosen),float(np.mean(norms)) if norms else None
    if device=='cuda':torch.cuda.reset_peak_memory_stats()
    stopped=stopper.wait>=stopper.patience
    if stopper.wait<stopper.patience:
        for epoch in range(epoch_start,max_epochs+1):
            started=time.monotonic();tl,norm=epoch_pass(ids['train'],True);vl,_=epoch_pass(ids['validation'],False)
            scheduler.step(vl);improved,stopped=stopper.observe(vl,epoch)
            row={'epoch':epoch,'train_loss':tl,'validation_loss':vl,'learning_rate':optimizer.param_groups[0]['lr'],
                 'gradient_norm_before_clip':norm,'elapsed_seconds':time.monotonic()-started,'batch_size_actual':batch_size}
            history.append(row)
            if improved:torch.save({'state_dict':model.state_dict(),'config':config,'best_epoch':epoch},directory/'best.pt')
            torch.save({'model':model.state_dict(),'optimizer':optimizer.state_dict(),'scheduler':scheduler.state_dict(),
                'stopper':asdict(stopper),'history':history,'epoch':epoch,'config':config,
                'torch_rng':torch.get_rng_state(),'numpy_rng':rng.bit_generator.state,
                'cuda_rng':torch.cuda.get_rng_state() if device=='cuda' else None},directory/'resume.pt')
            print(f'M5 {group}/{architecture}/{head}/seed={seed} epoch={epoch} train={tl:.6f} val={vl:.6f} best={stopper.best_epoch}',flush=True)
            if stopped:break
            if pause_after_epoch is not None and epoch>=pause_after_epoch:
                raise InterruptedError('RESEARCH_TRAINING_PAUSED_AFTER_DURABLE_CHECKPOINT')
    best=torch.load(directory/'best.pt',map_location=device,weights_only=True)
    if best['config']!=config or best['best_epoch']!=stopper.best_epoch:raise ValueError('BEST_CHECKPOINT_PROVENANCE_MISMATCH')
    model.load_state_dict(best['state_dict']);model.eval()
    def predict(indices):
        outputs=[]
        with torch.inference_mode():
            for start in range(0,len(indices),batch_size):
                xx=torch.from_numpy(X[np.asarray(indices[start:start+batch_size])]).to(device)
                outputs.append(model(xx).float().cpu().numpy()*sd+mu)
        return np.concatenate(outputs)
    validation=predict(ids['validation']);cal_pred=predict(ids['calibration']);test_pred=predict(ids['test'])
    calibration=fit_calibration(y[ids['calibration']],cal_pred,bundle.rows,bundle.split)
    calibrated=apply_calibration(test_pred,calibration)
    result={'config':config,'epochs':len(history),'best_epoch':stopper.best_epoch,
        'early_stopping_epoch':history[-1]['epoch'] if stopped else None,
        'convergence_status':'EARLY_STOPPED_VALIDATION_PATIENCE' if stopped else 'MAX_EPOCHS_REACHED_NOT_PROVEN_CONVERGED',
        'restored_best_checkpoint':True,'checkpoint_sha256':_sha(directory/'best.pt'),
        'validation':metrics(y[ids['validation']],validation),'test_raw':metrics(y[ids['test']],test_pred),
        'test_calibrated':metrics(y[ids['test']],calibrated),'calibration':calibration,
        'gpu_peak_bytes':torch.cuda.max_memory_allocated() if device=='cuda' else 0,
        'elapsed_seconds':time.monotonic()-total_started,'history':history,'directory':str(directory)}
    (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    np.savez_compressed(directory/'predictions.npz',test_raw=test_pred,test_calibrated=calibrated,validation=validation,calibration=cal_pred)
    del model,optimizer
    if device=='cuda':torch.cuda.empty_cache()
    return result
