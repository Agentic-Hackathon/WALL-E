"""LangGraph agent-state example. Optional install: langgraph, langgraph-checkpoint-sqlite.

MemorySaver is session-only; SqliteSaver persists graph checkpoints across restarts.
Agent may never initiate exchange orders: this graph has no trading/withdrawal tools.
"""
from typing import TypedDict
from pathlib import Path
from .audit import AuditStore
from .strategy import Parameters,decision

class State(TypedDict, total=False):
    predicted_log_return:float
    equity_tmn:float
    cash_tmn:float
    price_tmn:float
    peak_tmn:float
    action:str
    reason:str
    notional_tmn:float

def run_demo(observed_state: State, fee_rate: float, *, checkpoint_db='state/graph.sqlite',
             audit_db='state/graph_audit.sqlite', thread_id='strategy-main', durable=True):
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.memory import MemorySaver
    from langgraph.checkpoint.sqlite import SqliteSaver
    required={'predicted_log_return','equity_tmn','cash_tmn','price_tmn','peak_tmn'}
    if not required.issubset(observed_state):
        raise ValueError('Provide all externally observed market and portfolio fields; no fixture state exists')
    p=Parameters(fee_rate=fee_rate)
    def evaluate(s:State)->State:
        act,why,amount=decision(s['predicted_log_return'],s['cash_tmn'],0.,
                                s['price_tmn'],s['equity_tmn'],s['peak_tmn'],p)
        return {'action':act,'reason':why,'notional_tmn':amount}
    def persist(s:State)->State:
        log=AuditStore(audit_db)
        log.record('GRAPH_DECISION',dict(s))
        log.remember('last_graph_decision',dict(s))
        log.close()
        return {}
    builder=StateGraph(State)
    builder.add_node('predictive_decision',evaluate)
    builder.add_node('durable_audit',persist)
    builder.add_edge(START,'predictive_decision')
    builder.add_edge('predictive_decision','durable_audit')
    builder.add_edge('durable_audit',END)
    Path(checkpoint_db).parent.mkdir(parents=True,exist_ok=True)
    if durable:
        # Supply proper persistent checkpointer. Must not use ephemeral-only MemorySaver for restart recovery.
        import sqlite3
        conn=sqlite3.connect(checkpoint_db,check_same_thread=False)
        checkpoint=SqliteSaver(conn)
    else:
        checkpoint=MemorySaver()
    graph=builder.compile(checkpointer=checkpoint)
    result=graph.invoke(observed_state, {'configurable':{'thread_id':thread_id}})
    if durable:conn.close()
    return result

if __name__=='__main__':
    raise SystemExit('Use run_demo(observed_state=..., fee_rate=...) with REAL verified market inputs')
