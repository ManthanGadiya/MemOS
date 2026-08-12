// Typed REST client for the MemOS dashboard (docs/Dashboard.md section 6).
// Every call unwraps the documented envelope (API.md section 4): a failed
// response throws ApiError with the kernel error code and message.

import type {
  AddRelationshipInput,
  AuditLogPage,
  Config,
  CreateMemoryInput,
  DashboardHealth,
  Envelope,
  ListMemoriesParams,
  MemoryObject,
  MemoryVersion,
  Relationship,
  SearchInput,
  SearchResult,
  Statistics,
  UpdateMemoryInput,
} from "./types";

const BASE_URL = "/api/v1";

export class ApiError extends Error {
  readonly code: string;
  readonly details?: Record<string, unknown>;

  constructor(code: string, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (cause) {
    throw new ApiError(
      "NETWORK_ERROR",
      `Cannot reach the MemOS API at ${BASE_URL}. Is the backend running?`,
    );
  }

  let body: Envelope<T>;
  try {
    body = (await response.json()) as Envelope<T>;
  } catch {
    throw new ApiError(
      "BAD_RESPONSE",
      `Backend returned non-JSON with status ${response.status}.`,
    );
  }

  if (!body.success || body.error) {
    throw new ApiError(
      body.error?.code ?? "UNKNOWN_ERROR",
      body.error?.message ?? "Unknown API error.",
      body.error?.details,
    );
  }
  return body.data;
}

function queryString(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item));
    } else {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export const api = {
  getStatistics(): Promise<Statistics> {
    return request<Statistics>("/dashboard/statistics");
  },

  getHealth(): Promise<DashboardHealth> {
    return request<DashboardHealth>("/dashboard/health");
  },

  getLogs(params: {
    operation?: string;
    result?: string;
    limit?: number;
    offset?: number;
  }): Promise<AuditLogPage> {
    return request<AuditLogPage>(`/dashboard/logs${queryString(params)}`);
  },

  getConfig(): Promise<Config> {
    return request<Config>("/config");
  },

  listMemories(params: ListMemoriesParams = {}): Promise<MemoryObject[]> {
    return request<MemoryObject[]>(`/memories${queryString(params)}`);
  },

  getMemory(memoryId: string): Promise<MemoryObject> {
    return request<MemoryObject>(`/memories/${encodeURIComponent(memoryId)}`);
  },

  createMemory(input: CreateMemoryInput): Promise<MemoryObject> {
    return request<MemoryObject>("/memories", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  updateMemory(memoryId: string, input: UpdateMemoryInput): Promise<MemoryObject> {
    return request<MemoryObject>(`/memories/${encodeURIComponent(memoryId)}`, {
      method: "PUT",
      body: JSON.stringify(input),
    });
  },

  deleteMemory(memoryId: string): Promise<{ memory_id: string; deleted: boolean }> {
    return request<{ memory_id: string; deleted: boolean }>(
      `/memories/${encodeURIComponent(memoryId)}`,
      { method: "DELETE" },
    );
  },

  archiveMemory(memoryId: string): Promise<MemoryObject> {
    return request<MemoryObject>(`/memories/${encodeURIComponent(memoryId)}/archive`, {
      method: "PUT",
    });
  },

  restoreMemory(memoryId: string): Promise<MemoryObject> {
    return request<MemoryObject>(`/memories/${encodeURIComponent(memoryId)}/restore`, {
      method: "PUT",
    });
  },

  search(input: SearchInput): Promise<SearchResult[]> {
    return request<SearchResult[]>("/search", {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  listVersions(memoryId: string): Promise<MemoryVersion[]> {
    return request<MemoryVersion[]>(
      `/memories/${encodeURIComponent(memoryId)}/versions`,
    );
  },

  getRelated(memoryId: string): Promise<Relationship[]> {
    return request<Relationship[]>(
      `/memories/${encodeURIComponent(memoryId)}/relationships`,
    );
  },

  createRelationship(
    memoryId: string,
    input: AddRelationshipInput,
  ): Promise<Relationship> {
    return request<Relationship>(`/memories/${encodeURIComponent(memoryId)}/relationships`, {
      method: "POST",
      body: JSON.stringify(input),
    });
  },

  deleteRelationship(
    memoryId: string,
    relationshipId: string,
  ): Promise<{ relationship_id: string; deleted: boolean }> {
    return request<{ relationship_id: string; deleted: boolean }>(
      `/memories/${encodeURIComponent(memoryId)}/relationships/${encodeURIComponent(relationshipId)}`,
      { method: "DELETE" },
    );
  },
};
