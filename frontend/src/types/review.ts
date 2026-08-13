export type RuleStatus = 'violation' | 'warning' | 'insufficient' | 'passed';
export type ReviewMode = 'sample' | 'live';
export interface StatusCounts { violation: number; warning: number; insufficient: number; passed: number; }
export interface SafeIndicators { requiresReview?: boolean; unresolvedFields?: string[]; evaluatedSubchecks?: number; fieldAliases?: string[]; }
export interface BriefRule { id: string; number: number; title: string; status: RuleStatus; }
export interface RuleDetail extends BriefRule { conclusion?: string; llmAnalysis?: string; legalBasis?: string; evidenceLocations?: string; matchedText?: string; missingInputs?: string; confidence?: number; indicators?: SafeIndicators; }
export interface ReviewDocument { id: string; fileName: string; overallConclusion: RuleStatus; counts: StatusCounts & { executionFailed: number }; rules: BriefRule[]; detailAvailable: boolean; }
export interface ReviewSummary { schemaVersion: string; reviewId: string; mode: ReviewMode; sourceFiles: string[]; overallConclusion: RuleStatus; completedDocuments: number; failedDocuments: number; validDecisionCount: number; executionFailedCount: number; counts: StatusCounts; documents: ReviewDocument[]; }
export interface DocumentDetail { schemaVersion: string; reviewId: string; documentId: string; fileName: string; overallConclusion: RuleStatus; rules: RuleDetail[]; }
export interface CreateReviewInput { files: File[]; mode: ReviewMode; }
export interface ReviewJob { id: string; mode: ReviewMode; status: 'queued' | 'processing' | 'completed' | 'failed'; }
