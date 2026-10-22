from __future__ import annotations
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from .features import make_features, future_label, COLUMNS

def train_at_training_boundary(df, boundary, horizon=3):
    """Train strictly on causal examples whose labels end before boundary.

    Test OHLCV exists only to make finite labels; all indices used for training
    and their label intervals are before the held-out test boundary.
    """
    if len(df)<330 or not 200 <= boundary <= len(df):
        raise ValueError('Need >=330 candles and valid training cutoff')
    features=make_features(df)
    target=future_label(df,horizon)
    # Preserve v2 semantics for reproducible existing replays.
    train_idx=list(range(36,max(36,boundary-horizon-1)))
    valid=[i for i in train_idx if features.loc[i,COLUMNS].notna().all() and np.isfinite(target.iloc[i])]
    if len(valid)<150:
        raise ValueError('Insufficient training rows after label purge')
    model=HistGradientBoostingRegressor(max_iter=120,max_leaf_nodes=9,min_samples_leaf=25,
                                         learning_rate=.045,l2_regularization=1.0,
                                         early_stopping=False,random_state=31)
    model.fit(features.loc[valid,COLUMNS].to_numpy(),target.iloc[valid].to_numpy())
    return model,features,boundary


def train(df,horizon=3,fraction=.70):
    if len(df)<330:raise ValueError('Need >=330 candles; collect more history')
    return train_at_training_boundary(df,int(len(df)*fraction),horizon)


def train_cutoff(df,cutoff,horizon=3):
    return train_at_training_boundary(df,cutoff,horizon)

def predict(model,features,i):
    row=features.loc[i,COLUMNS]
    if row.isna().any():return float('nan')
    return float(model.predict(row.to_numpy(dtype=float).reshape(1,-1))[0])
