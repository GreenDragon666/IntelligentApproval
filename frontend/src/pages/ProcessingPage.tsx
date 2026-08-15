import { AlertTriangle, ArrowLeft, Check, FileSearch, RefreshCw, ScanSearch, ShieldCheck } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { hasReviewBackend, reviewService } from '../services/reviewService';
import type { ReviewProgress } from '../types/review';

const steps = [
  ['文件结构识别', '识别章节、表格与关键条款', FileSearch, ['queued', 'extracting']],
  ['规则并行审查', '执行规则匹配与语义审查', ScanSearch, ['matching', 'checking']],
  ['生成审查报告', '汇总结论、依据与证据', ShieldCheck, ['finalizing', 'completed']],
] as const;

export function ProcessingPage() {
  const [demoProgress, setDemoProgress] = useState(8);
  const [job, setJob] = useState<ReviewProgress>();
  const [error, setError] = useState('');
  const [retrying, setRetrying] = useState(false);
  const navigate = useNavigate();
  const { id = 'sample-review' } = useParams();
  const [params] = useSearchParams();
  const mode = params.get('mode') === 'live' ? 'live' : 'sample';
  const live = hasReviewBackend && mode === 'live';
  const progress = live ? job?.progress ?? 0 : demoProgress;

  useEffect(() => {
    if (live) return;
    const timer = window.setInterval(() => setDemoProgress(value => Math.min(100, value + 7)), 160);
    return () => window.clearInterval(timer);
  }, [live]);

  useEffect(() => {
    if (!live) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const next = await reviewService.getReviewStatus(id);
        if (!active) return;
        setJob(next);
        setError('');
        if (next.status === 'completed') {
          navigate(`/reviews/${encodeURIComponent(id)}/overview`, { replace: true });
          return;
        }
        if (next.status === 'failed') {
          setError(next.errorMessage || '审查任务执行失败，请联系管理员查看任务日志。');
          return;
        }
        timer = window.setTimeout(poll, 1500);
      } catch {
        if (!active) return;
        setError('暂时无法获取审查进度，系统将自动重试。');
        timer = window.setTimeout(poll, 3000);
      }
    };
    void poll();
    return () => { active = false; if (timer) window.clearTimeout(timer); };
  }, [id, live, navigate]);

  useEffect(() => {
    if (live || demoProgress !== 100) return;
    const timer = window.setTimeout(() => navigate(`/reviews/${encodeURIComponent(id)}/overview`), 500);
    return () => window.clearTimeout(timer);
  }, [demoProgress, id, live, navigate]);

  const activeStep = useMemo(() => {
    if (!live) return Math.min(2, Math.floor(progress / 34));
    const index = steps.findIndex(([, , , stages]) => stages.some(stage => stage === (job?.stage || 'queued')));
    return Math.max(0, index);
  }, [job?.stage, live, progress]);
  const retry = async () => {
    setRetrying(true);
    try {
      await reviewService.retryReview(id);
      window.location.reload();
    } catch {
      setError('重新提交失败，请检查后端和任务日志后再试。');
      setRetrying(false);
    }
  };

  return <section className="processing-card">
    <header className="processing-header">
      <div>
        <span className="eyebrow">审查任务 · {id}</span>
        <h1>{live ? '正在执行文件审查' : '正在准备示例审查报告'}</h1>
        <p>{live ? `正在处理 ${job?.totalDocuments ?? 0} 份文件，完成后将自动进入审查总览。` : '当前未连接后端，本步骤演示任务流转并加载内置报告。'}</p>
      </div>
      <span className="task-state">{error && job?.status === 'failed' ? '执行失败' : job?.status === 'queued' ? '排队中' : '处理中'}</span>
    </header>
    <div className="processing-body">
      <div className="scan-visual"><div className="scan-line"/><ShieldCheck/></div>
      <div className="progress-content">
        <div className="progress-meta"><b>{progress}%</b><span>{progress === 100 ? '报告已就绪' : '正在处理，可以安全离开此页面后再返回'}</span></div>
        <div className="progress-track"><i style={{ width: `${progress}%` }}/></div>
        <div className="processing-steps">{steps.map(([title, description, Icon], index) => {
          const done = index < activeStep || progress === 100;
          const active = index === activeStep && !done;
          return <div className={active ? 'active' : done ? 'done' : ''} key={title}><span>{done ? <Check/> : <Icon/>}</span><div><b>{title}</b><small>{description}</small></div></div>;
        })}</div>
        {error && <div className="inline-error" role="alert"><AlertTriangle size={17}/>{error}</div>}
      </div>
    </div>
    <footer className="processing-footer">
      <Link className="secondary-button" to="/"><ArrowLeft size={17}/>返回上传</Link>
      {error && live && job?.status === 'failed' ? <button className="secondary-button" disabled={retrying} onClick={retry}><RefreshCw size={17}/>{retrying ? '正在重新提交…' : '重试失败文件'}</button> : error && live ? <button className="secondary-button" onClick={() => window.location.reload()}><RefreshCw size={17}/>重新连接</button> : <span>{live ? '数据由审批服务处理' : '演示模式不会分析本地文件'}</span>}
    </footer>
  </section>;
}
