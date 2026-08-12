// TypeScript mirror of the MemOS REST API contracts (docs/API.md and
// docs/Dashboard.md section 7). Field names match the backend schemas exactly.

export interface Envelope<T> {
  success: boolean;
  message?: string;
  data: T;
  metadata?: Record<string, unknown>;
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export interface MemoryObject {
  content: string;
  title: string;
  source: string;
  summary: string;
  memory_id: string;
  namespace: string;
  owner_id: string;
  type: string;
  permission: string;
  tags: string[];
  metadata: Record<string, unknown>;
  state: string;
  version: number;
  created_at: string;
  updated_at: string;
  last_accessed_at: string | null;
  access_count: number;
  importance: number;
  importance_category: string;
  confidence: number;
  embedding: number[] | null;
}

export interface SearchResult {
  memory: MemoryObject;
  score: number;
  similarity: number;
  importance: number;
  recency: number;
  graph_connectivity: number;
}

export interface Relationship {
  relationship_id: string;
  source_id: string;
  target_id: string;
  type: string;
  weight: number;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface MemoryVersion {
  memory_id: string;
  version: number;
  content: string;
  change_type: string;
  created_at: string;
  diff: Record<string, unknown>;
  metadata: Record<string, unknown>;
}

export interface Statistics {
  memory_count: number;
  relationship_count: number;
  audit_count: number;
}

export interface DashboardHealth {
  status: string;
  app: string;
  version: string;
  storage_backend: string;
  embedding_backend: string;
  kernel: string;
  metadata_store: string;
}

export interface AuditRecord {
  timestamp: string;
  request_id: string;
  memory_id: string | null;
  operation: string;
  principal_id: string;
  result: string;
  created_by: string;
  modified_by: string;
  modified_at: string;
  operation_type: string;
  details: Record<string, unknown>;
}

export interface AuditLogPage {
  records: AuditRecord[];
  total: number;
}

export type Config = Record<string, string | number | boolean>;

export interface ListMemoriesParams {
  owner_id?: string;
  memory_type?: string;
  state?: string;
  tags?: string[];
  limit?: number;
  offset?: number;
}

export interface CreateMemoryInput {
  content: string;
  title?: string;
  source?: string;
  summary?: string;
  owner_id?: string;
  memory_type?: string;
  namespace?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
  permission?: string;
}

export interface UpdateMemoryInput {
  content?: string;
  memory_type?: string;
  namespace?: string;
  title?: string;
  source?: string;
  summary?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

export interface SearchInput {
  query: string;
  top_k?: number;
  owner_id?: string;
  memory_type?: string;
  state?: string;
  tags?: string[];
  graph_expansion?: boolean;
}

export interface AddRelationshipInput {
  target_id: string;
  relationship_type?: string;
  weight?: number;
  metadata?: Record<string, unknown>;
}
