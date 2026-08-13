import { AlertTriangle, ArrowRight, CheckCircle2, CircleMinus, FileCheck2, Plus, RefreshCw, ShieldAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Pagination, RuleRows, RuleToolbar, StatusFilter, useRuleFilter } from '../components/RuleList';
import { StatusBadge } from '../components/StatusBadge';
import { reviewService } from '../services/reviewService';
import type { ReviewSummary, RuleStatus } from '../types/review';

const statusLabel: Record<RuleStatus,string>={violation:'存在违规项',warning:'存在预警项',insufficient:'存在输入不足',passed:'审查通过'};
const toPage=(value:string|null)=>Math.max(1,Number.parseInt(value||'1',10)||1);
const toStatus=(value:string|null):StatusFilter=>value==='violation'||value==='warning'||value==='insufficient'||value==='passed'?value:'all';

export function OverviewPage(){
  const {id='sample-review'}=useParams();
  const [params,setParams]=useSearchParams();
  const [data,setData]=useState<ReviewSummary>();
  const [error,setError]=useState('');
  const load=useCallback(()=>{setError('');reviewService.getReview(id).then(setData).catch(()=>setError('审查报告加载失败，请检查数据服务后重试。'));},[id]);
  useEffect(load,[load]);
  const tab=params.get('document')||data?.documents[0]?.id||'';
  const query=params.get('query')||'';
  const status=toStatus(params.get('status'));
  const page=toPage(params.get('page'));
  const update=(changes:Record<string,string|number|null>)=>setParams(current=>{const next=new URLSearchParams(current);Object.entries(changes).forEach(([key,value])=>{if(value===null||value===''||value==='all'||value===1)next.delete(key);else next.set(key,String(value));});return next;});
  const doc=data?.documents.find(item=>item.id===tab)||data?.documents[0];
  const result=useRuleFilter(doc?.rules||[],query,status,page);
  const total=data?data.counts.violation+data.counts.warning+data.counts.insufficient+data.counts.passed:0;
  const metrics=useMemo(()=>data?([['违规',data.counts.violation,'violation',ShieldAlert],['预警',data.counts.warning,'warning',AlertTriangle],['输入不足',data.counts.insufficient,'insufficient',CircleMinus],['通过',data.counts.passed,'passed',CheckCircle2]] as const):[],[data]);
  const donut=useMemo(()=>{if(!data||!total)return 'conic-gradient(#e8edf3 0 100%)';let cursor=0;const colors={violation:'var(--danger)',warning:'var(--warning)',insufficient:'var(--muted-status)',passed:'var(--success)'};return `conic-gradient(${(['violation','warning','insufficient','passed'] as RuleStatus[]).map(key=>{const start=cursor;cursor+=data.counts[key]/total*100;return `${colors[key]} ${start}% ${cursor}%`;}).join(',')})`;},[data,total]);
  const overviewPath=`/reviews/${encodeURIComponent(id)}/overview${params.toString()?`?${params}`:''}`;
  if(error)return <div className="state-card"><ShieldAlert/><h2>无法加载报告</h2><p>{error}</p><div className="state-actions"><Link className="secondary-button" to="/">返回新建审查</Link><button className="primary-button" onClick={load}><RefreshCw size={17}/>重新加载</button></div></div>;
  if(!data)return <div className="state-card loading"><span className="spinner"/><h2>正在加载审查报告</h2></div>;
  return <div className="report-page">
    <section className="report-header"><div><span className="eyebrow">审查任务 · {data.reviewId}</span><h1>审查结果总览</h1><p>{data.completedDocuments} 份文件已完成 · {data.failedDocuments} 份处理失败 · {data.validDecisionCount} 项有效决策</p></div><div className="header-actions"><Link className="secondary-button" to="/"><Plus size={16}/>新建审查</Link><div className="overall"><StatusBadge status={data.overallConclusion}/><b>{statusLabel[data.overallConclusion]}</b><span>{data.counts.violation?`建议优先复核 ${data.counts.violation} 项违规决定`:'未发现明确违规决定'}</span></div></div></section>
    <section className="metric-grid">{metrics.map(([label,value,cls,Icon])=><article className={`metric metric-${cls}`} key={label}><span><Icon/></span><div><small>{label}</small><b>{value}</b></div><i>{total?Math.round(value/total*100):0}%</i></article>)}</section>
    <section className="insight-grid"><article className="panel"><div><span className="eyebrow">决策分布</span><h2>规则状态构成</h2></div><div className="donut-wrap"><div className="donut" style={{background:donut}}><span><b>{total}</b><small>规则决策</small></span></div><ul>{metrics.map(([label,value,cls])=><li key={label}><i className={`dot ${cls}`}/><span>{label}</span><b>{value}</b></li>)}</ul></div></article><article className="panel"><div><span className="eyebrow">文件对比</span><h2>文件风险分布</h2></div>{data.documents.map(document=>{const documentTotal=document.counts.violation+document.counts.warning+document.counts.insufficient+document.counts.passed;return <div className="bar-row" key={document.id}><header><span>{document.fileName}</span><b>{document.counts.violation+document.counts.warning} 项需关注</b></header><div className="stacked">{(['violation','warning','insufficient','passed'] as RuleStatus[]).map(key=><i key={key} className={key} style={{width:`${documentTotal?document.counts[key]/documentTotal*100:0}%`}}/>)}</div></div>})}</article></section>
    <section><div className="section-title"><div><span className="eyebrow">审查文件</span><h2>文件审查结果</h2></div><span>执行失败 {data.executionFailedCount}</span></div><div className="document-grid">{data.documents.map(document=><Link className="document-card" key={document.id} to={`/reviews/${encodeURIComponent(id)}/documents/${encodeURIComponent(document.id)}?returnTo=${encodeURIComponent(overviewPath)}`}><header><span><FileCheck2/></span><StatusBadge status={document.overallConclusion}/></header><h3>{document.fileName}</h3><p>{document.detailAvailable?'可查看完整规则结论、依据与证据':'当前仅提供规则简报清单'}</p><div className="mini-counts"><span><b>{document.counts.violation}</b>违规</span><span><b>{document.counts.warning}</b>预警</span><span><b>{document.counts.insufficient}</b>不足</span><span><b>{document.counts.passed}</b>通过</span></div><footer>查看文件详情 <ArrowRight size={16}/></footer></Link>)}</div></section>
    {doc&&<section className="panel rules-panel"><header><div><span className="eyebrow">完整规则 · {doc.rules.length}</span><h2>规则决策清单</h2></div><div className="tabs">{data.documents.map(document=><button className={doc.id===document.id?'active':''} onClick={()=>update({document:document.id,query:null,status:null,page:null})} key={document.id}>{document.fileName}</button>)}</div></header><RuleToolbar query={query} onQuery={value=>update({query:value,page:null})} status={status} onStatus={value=>update({status:value,page:null})}/>{result.items.length?<RuleRows rules={result.items}/>:<div className="empty-state">没有符合当前条件的规则</div>}<Pagination page={Math.min(page,result.pages)} pages={result.pages} onPage={value=>update({page:value})}/></section>}
  </div>;
}
