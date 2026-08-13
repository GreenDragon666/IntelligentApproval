import { AlertTriangle, CheckCircle2, CircleMinus, ShieldAlert } from 'lucide-react';
import type { RuleStatus } from '../types/review';
const meta = { violation: ['违规', ShieldAlert], warning: ['预警', AlertTriangle], insufficient: ['输入不足', CircleMinus], passed: ['通过', CheckCircle2] } as const;
export function StatusBadge({ status }: { status: RuleStatus }) { const [label, Icon] = meta[status]; return <span className={`status status-${status}`}><Icon size={14}/>{label}</span>; }
