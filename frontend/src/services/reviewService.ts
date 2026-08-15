import type { CreateReviewInput, DocumentDetail, ReviewJob, ReviewProgress, ReviewSummary } from '../types/review';
import { normalizeDocumentDetail, normalizeReviewJob, normalizeReviewSummary } from './reviewNormalizer';
export interface ReviewService {
  createReview(input: CreateReviewInput): Promise<ReviewJob>;
  retryReview(id: string): Promise<ReviewJob>;
  getReviewStatus(id: string): Promise<ReviewProgress>;
  getReview(id: string): Promise<ReviewSummary>;
  getDocument(id: string, documentId: string): Promise<DocumentDetail | null>;
}
const readJson = async (url: string): Promise<unknown> => {
  const response = await fetch(url);
  if (!response.ok) throw new Error('无法读取示例审查数据');
  return response.json() as Promise<unknown>;
};
export class MockReviewService implements ReviewService {
  async createReview(input: CreateReviewInput): Promise<ReviewJob> { return normalizeReviewJob({ id: 'sample-review', mode: input.mode, status: 'processing' }); }
  async retryReview(): Promise<ReviewJob> { return normalizeReviewJob({ id: 'sample-review', mode: 'sample', status: 'processing' }); }
  async getReviewStatus(): Promise<ReviewProgress> { return { id: 'sample-review', mode: 'sample', status: 'processing', internalStatus: 'processing', stage: 'checking', progress: 50, totalDocuments: 1, completedDocuments: 0, failedDocuments: 0, documents: [] }; }
  async getReview(): Promise<ReviewSummary> { return normalizeReviewSummary(await readJson('/data/review-summary.sample.json')); }
  async getDocument(_id: string, documentId: string): Promise<DocumentDetail | null> {
    if (documentId !== 'doc-1') return null;
    return normalizeDocumentDetail(await readJson('/data/document-detail.sample.json'));
  }
}
export class HttpReviewService implements ReviewService {
  private readonly baseUrl: string;
  constructor(baseUrl = '/api') { this.baseUrl = baseUrl.replace(/\/+$/, ''); }
  private async request(path: string, init?: RequestInit): Promise<unknown> {
    const response = await fetch(`${this.baseUrl}${path}`, init);
    if (!response.ok) throw new Error(`审查服务请求失败（${response.status}）`);
    return response.json() as Promise<unknown>;
  }
  async createReview(input: CreateReviewInput): Promise<ReviewJob> {
    const form = new FormData(); input.files.forEach(file => form.append('documents', file));
    return normalizeReviewJob(await this.request('/reviews', { method: 'POST', body: form }));
  }
  async getReviewStatus(id: string) { return this.request(`/reviews/${id}/status`) as Promise<ReviewProgress>; }
  async retryReview(id: string) { return normalizeReviewJob(await this.request(`/reviews/${id}/retry`, { method: 'POST' })); }
  async getReview(id: string) { return normalizeReviewSummary(await this.request(`/reviews/${id}`)); }
  async getDocument(id: string, documentId: string) { return normalizeDocumentDetail(await this.request(`/reviews/${id}/documents/${documentId}`)); }
}
export const hasReviewBackend = Boolean(import.meta.env.VITE_REVIEW_API_URL);
export const reviewService: ReviewService = hasReviewBackend ? new HttpReviewService(import.meta.env.VITE_REVIEW_API_URL) : new MockReviewService();
