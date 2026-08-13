import type { BriefRule, DocumentDetail, ReviewDocument, ReviewJob, ReviewMode, ReviewSummary, RuleDetail, RuleStatus, SafeIndicators, StatusCounts } from '../types/review';

type RecordValue = Record<string, unknown>;
const statuses: RuleStatus[] = ['violation', 'warning', 'insufficient', 'passed'];
const object = (value: unknown): RecordValue => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as RecordValue : {};
const alias = (source: RecordValue, ...keys: string[]) => keys.map(key => source[key]).find(value => value !== undefined && value !== null);
const text = (value: unknown): string | undefined => {
  if (typeof value === 'string') return value.trim() || undefined;
  if (Array.isArray(value)) {
    const values = value.filter(item => typeof item === 'string').map(item => item.trim()).filter(Boolean);
    return values.length ? values.join('\n') : undefined;
  }
};
const stringList = (value: unknown): string[] | undefined => {
  const values = Array.isArray(value) ? value : typeof value === 'string' ? [value] : [];
  const safe = values.filter(item => typeof item === 'string').map(item => item.trim()).filter(Boolean);
  return safe.length ? safe : undefined;
};
const number = (value: unknown, fallback = 0): number => typeof value === 'number' && Number.isFinite(value) ? value : typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value)) ? Number(value) : fallback;
const integer = (value: unknown, fallback = 0): number => Math.max(0, Math.trunc(number(value, fallback)));
const boolean = (value: unknown): boolean | undefined => typeof value === 'boolean' ? value : value === 1 || value === 'true' ? true : value === 0 || value === 'false' ? false : undefined;
const status = (value: unknown, fallback: RuleStatus = 'insufficient'): RuleStatus => statuses.includes(value as RuleStatus) ? value as RuleStatus : fallback;
const mode = (value: unknown): ReviewMode => value === 'live' ? 'live' : 'sample';
const confidence = (value: unknown): number | undefined => {
  if (value === undefined || value === null || value === '') return undefined;
  let normalized = number(value, Number.NaN);
  if (!Number.isFinite(normalized)) return undefined;
  if (normalized > 1) normalized /= 100;
  return Math.min(1, Math.max(0, normalized));
};
const id = (value: unknown, fallback: string): string => text(value) ?? fallback;

function normalizeCounts(value: unknown, rules: BriefRule[] = []): StatusCounts & { executionFailed: number } {
  const source = object(value);
  const fromRules = (target: RuleStatus) => rules.filter(rule => rule.status === target).length;
  return {
    violation: integer(alias(source, 'violation', 'violations'), fromRules('violation')),
    warning: integer(alias(source, 'warning', 'warnings'), fromRules('warning')),
    insufficient: integer(alias(source, 'insufficient', 'insufficientInputs', 'insufficient_inputs'), fromRules('insufficient')),
    passed: integer(alias(source, 'passed', 'pass'), fromRules('passed')),
    executionFailed: integer(alias(source, 'executionFailed', 'execution_failed')),
  };
}

function normalizeIndicators(value: unknown): SafeIndicators | undefined {
  const source = object(value);
  const result: SafeIndicators = {};
  const requiresReview = boolean(alias(source, 'requiresReview', 'requires_review'));
  const unresolvedFields = stringList(alias(source, 'unresolvedFields', 'unresolved_fields'));
  const evaluated = alias(source, 'evaluatedSubchecks', 'evaluated_subchecks');
  const fieldAliases = stringList(alias(source, 'fieldAliases', 'field_aliases'));
  if (requiresReview !== undefined) result.requiresReview = requiresReview;
  if (unresolvedFields) result.unresolvedFields = unresolvedFields;
  if (evaluated !== undefined) result.evaluatedSubchecks = integer(evaluated);
  if (fieldAliases) result.fieldAliases = fieldAliases;
  return Object.keys(result).length ? result : undefined;
}

function normalizeRule(value: unknown, index: number, detailed: boolean): RuleDetail {
  const source = object(value);
  const rule: RuleDetail = {
    id: id(alias(source, 'id', 'ruleId', 'rule_id'), `rule-${index + 1}`),
    number: integer(alias(source, 'number', 'ruleNumber', 'rule_number'), index + 1),
    title: text(alias(source, 'title', 'ruleTitle', 'rule_title', 'name')) ?? `规则 ${index + 1}`,
    status: status(alias(source, 'status', 'result', 'decision')),
  };
  if (!detailed) return rule;
  const fields = {
    conclusion: text(alias(source, 'conclusion')),
    llmAnalysis: text(alias(source, 'llmAnalysis', 'llm_analysis')),
    legalBasis: text(alias(source, 'legalBasis', 'legal_basis')),
    evidenceLocations: text(alias(source, 'evidenceLocations', 'evidence_locations', 'evidenceLocation', 'evidence_location')),
    matchedText: text(alias(source, 'matchedText', 'matched_text')),
    missingInputs: text(alias(source, 'missingInputs', 'missing_inputs')),
    confidence: confidence(alias(source, 'confidence')),
    indicators: normalizeIndicators(alias(source, 'indicators')),
  };
  Object.entries(fields).forEach(([key, field]) => { if (field !== undefined) (rule as unknown as RecordValue)[key] = field; });
  return rule;
}

function normalizeDocument(value: unknown, index: number): ReviewDocument {
  const source = object(value);
  const rulesValue = alias(source, 'rules', 'ruleResults', 'rule_results');
  const rules = Array.isArray(rulesValue) ? rulesValue.map((rule, ruleIndex) => normalizeRule(rule, ruleIndex, false)) : [];
  const counts = normalizeCounts(alias(source, 'counts', 'statusCounts', 'status_counts'), rules);
  return {
    id: id(alias(source, 'id', 'documentId', 'document_id'), `doc-${index + 1}`),
    fileName: text(alias(source, 'fileName', 'file_name', 'name')) ?? `文件 ${index + 1}`,
    overallConclusion: status(alias(source, 'overallConclusion', 'overall_conclusion'), counts.violation ? 'violation' : counts.warning ? 'warning' : counts.insufficient ? 'insufficient' : 'passed'),
    counts,
    rules,
    detailAvailable: boolean(alias(source, 'detailAvailable', 'detail_available')) ?? false,
  };
}

export function normalizeReviewSummary(value: unknown): ReviewSummary {
  const source = object(value);
  const documentsValue = alias(source, 'documents', 'reviewDocuments', 'review_documents');
  const documents = Array.isArray(documentsValue) ? documentsValue.map(normalizeDocument) : [];
  const allRules = documents.flatMap(document => document.rules);
  const counts = normalizeCounts(alias(source, 'counts', 'statusCounts', 'status_counts'), allRules);
  const validTotal = counts.violation + counts.warning + counts.insufficient + counts.passed;
  return {
    schemaVersion: text(alias(source, 'schemaVersion', 'schema_version')) ?? '1.0',
    reviewId: id(alias(source, 'reviewId', 'review_id', 'id'), 'unknown-review'),
    mode: mode(alias(source, 'mode')),
    sourceFiles: stringList(alias(source, 'sourceFiles', 'source_files')) ?? documents.map(document => document.fileName),
    overallConclusion: status(alias(source, 'overallConclusion', 'overall_conclusion'), counts.violation ? 'violation' : counts.warning ? 'warning' : counts.insufficient ? 'insufficient' : 'passed'),
    completedDocuments: integer(alias(source, 'completedDocuments', 'completed_documents'), documents.length),
    failedDocuments: integer(alias(source, 'failedDocuments', 'failed_documents')),
    validDecisionCount: integer(alias(source, 'validDecisionCount', 'valid_decision_count'), validTotal),
    executionFailedCount: integer(alias(source, 'executionFailedCount', 'execution_failed_count'), documents.reduce((sum, document) => sum + document.counts.executionFailed, 0)),
    counts: { violation: counts.violation, warning: counts.warning, insufficient: counts.insufficient, passed: counts.passed },
    documents,
  };
}

export function normalizeDocumentDetail(value: unknown): DocumentDetail | null {
  if (value === null || value === undefined) return null;
  const source = object(value);
  const rulesValue = alias(source, 'rules', 'ruleResults', 'rule_results');
  const rules = Array.isArray(rulesValue) ? rulesValue.map((rule, index) => normalizeRule(rule, index, true)) : [];
  return {
    schemaVersion: text(alias(source, 'schemaVersion', 'schema_version')) ?? '1.0',
    reviewId: id(alias(source, 'reviewId', 'review_id'), 'unknown-review'),
    documentId: id(alias(source, 'documentId', 'document_id', 'id'), 'unknown-document'),
    fileName: text(alias(source, 'fileName', 'file_name', 'name')) ?? '未命名文件',
    overallConclusion: status(alias(source, 'overallConclusion', 'overall_conclusion')),
    rules,
  };
}

export function normalizeReviewJob(value: unknown): ReviewJob {
  const source = object(value);
  const jobStatus = alias(source, 'status');
  return {
    id: id(alias(source, 'id', 'reviewId', 'review_id'), 'unknown-review'),
    mode: mode(alias(source, 'mode')),
    status: jobStatus === 'queued' || jobStatus === 'processing' || jobStatus === 'completed' || jobStatus === 'failed' ? jobStatus : 'queued',
  };
}
