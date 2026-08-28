import { apiRequest } from './client';

export interface AnalysisDatasetSpectrum {
  id: string;
  title?: string | null;
  modality: string;
  state: string;
}

export interface AnalysisDataset {
  id: string;
  name: string;
  description?: string | null;
  modality: string;
  spectra: AnalysisDatasetSpectrum[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface AnalysisRun {
  id: string;
  dataset_id: string;
  analysis_type: 'pca' | 'pca_kmeans';
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled';
  execution_backend: 'local' | 'hosted';
  parameters: Record<string, number>;
  input_manifest: Array<Record<string, string | null>>;
  software_versions: Record<string, string>;
  quality_checks: Record<string, string | number | boolean>;
  output?: {
    spectrum_ids: string[];
    scores: number[][];
    explained_variance_ratio: number[];
    cluster_labels?: number[];
  } | null;
  citation?: Record<string, string> | null;
  output_hash?: string | null;
  attempt_count: number;
  max_attempts: number;
  cancel_requested: boolean;
  error_message?: string | null;
  created_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export async function createAnalysisDataset(payload: {
  name: string;
  description?: string;
  spectrum_ids: string[];
}): Promise<AnalysisDataset> {
  return apiRequest<AnalysisDataset>('/analysis/datasets', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function createAnalysisRun(
  datasetId: string,
  payload: {
    analysis_type: 'pca' | 'pca_kmeans';
    components: number;
    grid_points: number;
    clusters?: number;
    execution_backend?: 'local';
  },
): Promise<AnalysisRun> {
  return apiRequest<AnalysisRun>(`/analysis/datasets/${datasetId}/runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getAnalysisRun(runId: string): Promise<AnalysisRun> {
  return apiRequest<AnalysisRun>(`/analysis/runs/${runId}`);
}

export async function cancelAnalysisRun(runId: string): Promise<AnalysisRun> {
  return apiRequest<AnalysisRun>(`/analysis/runs/${runId}/cancel`, { method: 'POST' });
}