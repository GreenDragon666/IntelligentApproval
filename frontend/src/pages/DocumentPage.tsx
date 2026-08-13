import { ArrowLeft, BrainCircuit, FileQuestion, MapPin, Quote, RefreshCw, Scale } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { Pagination, RuleRows, RuleToolbar, sortRules, StatusFilter, useRuleFilter } from '../components/RuleList';
import { StatusBadge } from '../components/StatusBadge';
import { reviewService } from '../services/reviewService';
import type { DocumentDetail, ReviewSummary, RuleDetail } from '../types/review';

const validReturnTo=(value:string|null,id:string)=>value?.startsWith(`/reviews/${encodeURIComponent(id)}/overview`)?value:`/reviews/${encodeURIComponent(id)}/overview`;
const toPage=(value:string|null)=>Math.max(1,Number.parseInt(value||'1',10)||1);
const toStatus=(value:string|null):StatusFilter=>value==='violation'||value==='warning'||value==='insufficient'||value==='passed'?value:'all';
function DetailBlock({icon:Icon,title,children,className=''}:{icon:typeof Scale;title:string;children?:string;className?:string}){if(!children)return null;return <section className={`detail-block ${className}`}><h3><Icon size={18}/>{title}</h3><p>{children}</p></section>}

export function DocumentPage(){
  const {id='sample-review',documentId='doc-1'}=useParams();
  const [params,setParams]=useSearchParams();
  const [summary,setSummary]=useState<ReviewSummary>();
  const [detail,setDetail]=useState<DocumentDetail|null>();
  const [loaded,setLoaded]=useState(false);
  const [error,setError]=useState('');
  const load=useCallback(()=>{setError('');setLoaded(false);Promise.all([reviewService.getReview(id),reviewService.getDocument(id,documentId)]).then(([nextSummary,nextDetail])=>{setSummary(nextSummary);setDetail(nextDetail);setLoaded(true);}).catch(()=>setError('文件审查结果加载失败，请检查数据服务后重试。'));},[id,documentId]);
  useEffect(load,[load]);
  const doc=summary?.documents.find(item=>item.id===documentId);
  const rules=useMemo(()=>sortRules(detail?.rules||doc?.rules||[]),[detail,doc]);
  const query=params.get('query')||'';
  const status=toStatus(params.get('status'));
  const page=toPage(params.get('page'));
  const returnTo=validReturnTo(params.get('returnTo'),id);
  const filtered=useRuleFilter(rules,query,status,page,10);
  const requested=params.get('rule');
  const selectedId=requested&&rules.some(rule=>rule.id===requested)?requested:rules[0]?.id;
  const selected=useMemo(()=>detail?.rules.find(rule=>rule.id===selectedId),[detail,selectedId]);
  const update=(changes:Record<string,string|number|null>)=>setParams(current=>{const next=new URLSearchParams(current);Object.entries(changes).forEach(([key,value])=>{if(value===null||value===''||value==='all'||value===1)next.delete(key);else next.set(key,String(value));});next.set('returnTo',returnTo);return next;});
  if(error)return <div className="state-card"><FileQuestion/><h2>无法加载文件结果</h2><p>{error}</p><div className="state-actions"><Link className="secondary-button" to={returnTo}><ArrowLeft size={17}/>返回总览</Link><button className="primary-button" onClick={load}><RefreshCw size={17}/>重新加载</button></div></div>;
  if(!loaded)return <div className="state-card loading"><span className="spinner"/><h2>正在加载规则详情</h2></div>;
  if(!doc)return <div className="state-card"><FileQuestion/><h2>未找到该文件</h2><p>报告中不存在请求的文件记录。</p><Link className="primary-button" to={returnTo}><ArrowLeft size={17}/>返回总览</Link></div>;
  return <div className="document-page"><header className="document-header"><div><Link to={returnTo}><ArrowLeft size={17}/>返回总览</Link><h1>{doc.fileName}</h1><p>共 {rules.length} 项规则 · {doc.counts.violation} 项违规 · {doc.counts.warning} 项预警 · {doc.counts.insufficient} 项输入不足</p></div><StatusBadge status={doc.overallConclusion}/></header><div className="master-detail"><aside className="rule-nav"><header><div><span className="eyebrow">规则导航</span><h2>审查规则</h2></div><span>{rules.length} 项</span></header><RuleToolbar query={query} onQuery={value=>update({query:value,page:null})} status={status} onStatus={value=>update({status:value,page:null})}/>{filtered.items.length?<RuleRows rules={filtered.items} selected={selectedId} onSelect={rule=>{update({rule:rule.id});if(window.innerWidth<900)document.querySelector('.detail-pane')?.scrollIntoView({behavior:'smooth'});}}/>:<div className="empty-state">无匹配规则</div>}<Pagination page={Math.min(page,filtered.pages)} pages={filtered.pages} onPage={value=>update({page:value})}/></aside><article className="detail-pane">{!doc.detailAvailable?<div className="no-detail"><FileQuestion/><h2>该文件暂无规则详情</h2><p>当前数据源仅提供规则清单。为避免生成未经数据支持的结论、法规依据或证据，详情区域不作推断。</p><Link className="secondary-button" to={returnTo}>返回总览</Link></div>:selected?<RuleDetailView rule={selected}/>:<div className="no-detail"><FileQuestion/><h2>暂无可显示的规则详情</h2><p>请选择有详情数据的规则，或返回总览查看简报。</p><Link className="secondary-button" to={returnTo}>返回总览</Link></div>}</article></div></div>;
}

function RuleDetailView({rule}:{rule:RuleDetail}){
  const primary=rule.conclusion||rule.llmAnalysis;
  const auxiliary=rule.conclusion&&rule.llmAnalysis&&rule.conclusion.trim()!==rule.llmAnalysis.trim()?rule.llmAnalysis:undefined;
  return <><header className="detail-title"><div><span className="rule-index">规则 {String(rule.number).padStart(2,'0')}</span><h2>{rule.title}</h2></div><StatusBadge status={rule.status}/></header><section className={`conclusion-box conclusion-${rule.status}`}><span>语义审查摘要</span><p>{primary||'当前数据未提供语义结论，建议结合原文件进行人工复核。'}</p></section>{auxiliary&&<DetailBlock icon={BrainCircuit} title="辅助分析" children={auxiliary}/>}<DetailBlock icon={Scale} title="法规依据" children={rule.legalBasis} className="legal-block"/><DetailBlock icon={MapPin} title="证据位置" children={rule.evidenceLocations} className="evidence-block"/><DetailBlock icon={Quote} title="命中原文与理由" children={rule.matchedText} className="matched-block"/><DetailBlock icon={FileQuestion} title="缺失输入" children={rule.missingInputs}/>{(rule.confidence!==undefined||rule.indicators)&&<div className="meta-strip">{rule.confidence!==undefined&&<span>置信度 <b>{Math.round(rule.confidence*100)}%</b></span>}{rule.indicators?.requiresReview!==undefined&&<span>{rule.indicators.requiresReview?'需要人工复核':'无需额外人工复核'}</span>}{rule.indicators?.unresolvedFields?.length&&<span>待确认字段：{rule.indicators.unresolvedFields.join('、')}</span>}{rule.indicators?.evaluatedSubchecks!==undefined&&<span>已完成子检查：{rule.indicators.evaluatedSubchecks}</span>}{rule.indicators?.fieldAliases?.length&&<span>识别字段：{rule.indicators.fieldAliases.join('、')}</span>}</div>}</>;
}
