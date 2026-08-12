# API Specification
**Project:** MemOS (Memory Operating System)
**Document Version:** 1.0
**Status:** Draft
**Protocol:** REST API (Version 1)
**Base URL**
```
/api/v1
```
**Related Documents**
- PRD.md
- SRS.md
- SystemArchitecture.md
- Database.md
- Algorithms.md
---
# 1. Purpose
The MemOS API provides a standardized interface for applications, AI agents, SDKs, and the Dashboard to interact with the Memory Kernel.
The API is responsible only for exposing functionality.
It is **not** responsible for
- business logic
- memory lifecycle
- retrieval algorithms
- storage management
Every request is forwarded to the Memory Kernel.
---
# 2. Design Principles
- RESTful
- Stateless
- JSON-based
- Versioned
- Deterministic
- Consistent response format
---
# 3. API Flow
```
Client
↓
REST API
↓
Memory Kernel
↓
Core Services
↓
Response
```
Applications never communicate directly with databases.
---
# 4. Standard Response Format
## Success
```json
{
  "success": true,
  "message": "Operation completed successfully.",
  "data": {},
  "metadata": {}
}
```
## Error
```json
{
  "success": false,
  "error": {
    "code": "MEMORY_NOT_FOUND",
    "message": "Requested memory does not exist."
  }
}
```
---
# 5. Memory Endpoints
## Create Memory
```
POST /memories
```
Creates a new Memory Object.
---
## Get Memory
```
GET /memories/{memory_id}
```
Returns a Memory Object.
---
## Update Memory
```
PUT /memories/{memory_id}
```
Creates a new version of the Memory Object.
---
## Delete Memory
```
DELETE /memories/{memory_id}
```
Marks the Memory Object as deleted.
---
## List Memories
```
GET /memories
```
Supports filtering by
- type
- owner
- lifecycle
- tags
---
## Archive Memory
```
PUT /memories/{memory_id}/archive
```
Moves the Memory Object to `ARCHIVED` (excluded from default retrieval).
---
## Restore Memory
```
PUT /memories/{memory_id}/restore
```
Restores the Memory Object to `ACTIVE`.
---
## Adjust Confidence
```
POST /memories/{memory_id}/confidence?adjustment=repeated_observation|contradiction
```
Applies the Algorithms.md §4.4 confidence adjustment
(`repeated_observation` +0.05, `contradiction` −0.15).
---
# 6. Search API
## Hybrid Search
```
POST /search
```
Supports
- natural language queries
- metadata filters
- tag filters
- memory type filters
Returns
- ranked Memory Objects
- explanation metadata
- confidence
- importance
---
# 7. Version Endpoints
Versions are nested under their parent Memory Object.
## List Versions
```
GET /memories/{memory_id}/versions
```
Returns all versions.
---
## Get Version
```
GET /memories/{memory_id}/versions/{version}
```
Returns a specific version.
---
# 8. Relationship Endpoints
Relationships are nested under their source Memory Object.
## Create Relationship
```
POST /memories/{memory_id}/relationships
```
---
## Delete Relationship
```
DELETE /memories/{memory_id}/relationships/{relationship_id}
```
---
## Get Related Memories
```
GET /memories/{memory_id}/relationships
```
Returns connected Memory Objects.
---
# 9. Dashboard Endpoints
```
GET /dashboard/statistics
GET /dashboard/health
GET /dashboard/logs
```
Used exclusively by the Dashboard.
---
# 10. System Endpoints
## Health Check
```
GET /health
```
Returns
- API status
- Kernel status
- Storage status
---
## Configuration
```
GET /config
```
Returns safe runtime configuration.
---
## System Status
```
GET /system/status
```
Returns runtime identity and per-store backend selection.
---
# 11. Error Codes
| Code | Meaning |
|------|---------|
| MEMORY_NOT_FOUND | Memory does not exist |
| VALIDATION_ERROR | Invalid request |
| PERMISSION_DENIED | Unauthorized operation |
| RELATIONSHIP_NOT_FOUND | Relationship missing |
| VERSION_NOT_FOUND | Version missing |
| STORAGE_ERROR | Database failure |
| INTERNAL_ERROR | Unexpected server error |
---
# 12. API Versioning
Current version
```
/api/v1
```
Future versions
```
/api/v2
/api/v3
```
Breaking changes require a new API version.
---
# 13. Security
Version 1 assumes local deployment.
Future versions may support
- API Keys
- OAuth2
- JWT
- RBAC
All permission validation remains inside the Memory Kernel.
---
# 14. API Principles
1. All requests pass through the Memory Kernel.
2. APIs remain stateless.
3. Responses use a consistent schema.
4. Business logic never resides in the API layer.
5. Every endpoint returns structured errors.
6. API versioning preserves backward compatibility.
---
# 15. Conclusion
The MemOS API provides a stable, versioned, and deterministic interface for interacting with the Memory Operating System.
It abstracts the internal architecture, ensuring clients communicate only with the Memory Kernel while remaining independent of storage implementations and internal services.
---