"""M8 bounded intelligence startup over existing DataSyncManager/NewsStore.

No historical news/book backdating. The news lease is shared with the legacy
Watch ingestion entry point. Pattern rebuild is queued, never catalog-blocking.
"""
import json,time
from pathlib import Path
from .atlas_data_sync import DataSyncManager
from .atlas_operational import _read_connection,_table
from .atlas_patterns import PatternIndex,DEFAULT_INDEX
from .atlas_news_ingestion import harvest
from .atlas_news_pipeline import NewsStore

def _source(**values):
    row={k:None for k in ('last_valid_observation','last_successful_fetch','missing_intervals','pending_work','source_unavailable','staleness','resume_cursor','retry_status')}
    row.update(values);return row

class IntelligenceSyncManager(DataSyncManager):
    def intelligence_status(self,session_dir,*,index_dir=DEFAULT_INDEX):
        now=time.time();sources={}
        last=self.lake.db.execute("SELECT max(last_ts) FROM chunks WHERE status='COMPLETE'").fetchone()[0]
        progress=dict(self.lake.db.execute('SELECT status,count(*) FROM download_progress GROUP BY status'))
        sources['ohlcv']=_source(last_valid_observation=last,last_successful_fetch=self.lake.db.execute('SELECT max(available_at) FROM chunk_observations').fetchone()[0],
            missing_intervals='SEE_DEMAND_PLAN; unknown unobserved history is not zero activity',pending_work=progress.get('FAILED',0),source_unavailable=progress.get('SOURCE_UNAVAILABLE',0),
            resume_cursor='catalog.sqlite.download_progress',retry_status=progress,staleness=now-last if last is not None else None)
        db=_read_connection(self.lake.root/'news.sqlite')
        try:
            if db and _table(db,'news_source_runs'):
                pending=db.execute("SELECT count(*) FROM news_article_status WHERE processing_status='PENDING_SENTIMENT'").fetchone()[0]
                runs=[dict(zip(('source','last_finished','last_success','failures'),r)) for r in db.execute("SELECT source,max(finished_at),max(CASE WHEN status='SUCCESS' THEN finished_at END),sum(status!='SUCCESS') FROM news_source_runs GROUP BY source")]
                sources['news']=_source(last_valid_observation=db.execute('SELECT max(first_observed_at) FROM news_documents').fetchone()[0],
                    last_successful_fetch={r['source']:r['last_success'] for r in runs},pending_work=pending,
                    source_unavailable=[r['source'] for r in runs if r['last_success'] is None],retry_status=runs,
                    resume_cursor='news.sqlite news_source_runs/news_sync_cursor_v8',missing_intervals='UNKNOWN_BEFORE_INSTRUMENTED_POLLING',
                    staleness='PER_SOURCE_TIMESTAMPS; past publication is not past observation')
            else:sources['news']=_source(pending_work='NEWS_STORE_NOT_INITIALIZED',source_unavailable=None)
        finally:
            if db:db.close()
        if (Path(index_dir)/'patterns.sqlite').exists():
            index=PatternIndex(index_dir,readonly=True)
            try:
                manifest=index.manifest();index.verify_sources()
                sources['patterns']=_source(last_valid_observation=manifest['created_at'],last_successful_fetch='LOCAL_VERIFIED_ARCHIVE_ONLY',
                    staleness=now-manifest['created_at'],resume_cursor=manifest['manifest_sha256'],pending_work='REBUILD_IN_NEW_DIRECTORY_WHEN_DEMAND_CHANGES',
                    missing_intervals=manifest['skipped'],source_unavailable=False,retry_status='IMMUTABLE_INDEX_CACHE')
            except ValueError as exc:sources['patterns']=_source(source_unavailable=True,pending_work=str(exc))
            finally:index.close()
        else:sources['patterns']=_source(pending_work='INDEX_BUILD_REQUIRED',source_unavailable=None)
        db=_read_connection(Path(session_dir)/'forward_observations.sqlite')
        try:
            if db and _table(db,'quotes'):
                last=db.execute('SELECT max(observed_epoch) FROM quotes').fetchone()[0]
                sources['order_books']=_source(last_valid_observation=last,last_successful_fetch=last,
                    staleness=now-last if last is not None else None,missing_intervals='ONLY_ACTUAL_RECEIPTS; no reconstruction from OHLCV',
                    pending_work='INDEPENDENT_60S_DEADLINE_SAMPLER',resume_cursor='quotes / deadline_queue_v7',retry_status='BOUNDED_SAMPLER_RETRIES')
                sources['forecast_outcomes']=_source(pending_work=dict(db.execute('SELECT status,count(*) FROM m6_predictions GROUP BY status')),
                    resume_cursor='m6_predictions/m6_outcomes/deadline_queue_v7',missing_intervals='late/missing future receipts remain UNSCORED')
            else:sources['order_books']=_source(pending_work='FIRST_REAL_SNAPSHOT_REQUIRED')
        finally:
            if db:db.close()
        sources['symbol_metadata']=_source(last_valid_observation=self.lake.db.execute('SELECT max(observed_at) FROM assets').fetchone()[0],
            resume_cursor='catalog.sqlite.assets',pending_work='public catalog refresh is explicit; spot precision != verified contest rules',source_unavailable=False)
        sources['native_derived']=_source(pending_work='NATIVE 1/60/1D FIRST; derived complete buckets only',resume_cursor='catalog.sqlite.chunks/chunk_observations')
        sources['cross_asset']=_source(pending_work='only aligned verified returns; no assumed zero correlation')
        sources['memory']=_source(resume_cursor=str(Path(session_dir)/'context_memory.sqlite'),pending_work='HASH/PIT_VERIFICATION_BEFORE_RETRIEVAL')
        sources['sentiment']=_source(pending_work='PENDING_SCORES_RETAINED',source_unavailable='FINBERT_CONTEST_LICENSE_NOT_AUTHORIZED',retry_status='NO_AUTOMATIC_WEIGHT_DOWNLOAD')
        return {'version':'ATLAS_INTELLIGENCE_SYNC_V1','observed_at':now,'sources':sources,
            'full_catalog_backfill_blocks_startup':False,'synthetic_gap_fill':False,'credentials_used':False}

    def sync_intelligence(self,session_dir,*,index_dir=DEFAULT_INDEX,news_enabled=True):
        # Candle demand already handled by the study's existing DataSync step;
        # do not download it a second time here.
        result={'ohlcv':'ALREADY_RECONCILED_BY_EXISTING_STUDY_DATASYNC','news':{'status':'NEWS_SYNC_DISABLED'}}
        if news_enabled:
            result['news']=harvest(self.lake,hours=48,retries=1,source_budget=4,
                score_sentiment=False,min_interval_seconds=300)
        result['status']=self.intelligence_status(session_dir,index_dir=index_dir)
        return result
