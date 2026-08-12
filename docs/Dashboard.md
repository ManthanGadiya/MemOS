# Dashboard Specification
**Project:** MemOS (Memory Operating System)
**Document Version:** 1.0
**Status:** Draft
**Stack:** React + TypeScript
**Related Documents**
- PRD.md
- SRS.md
- SystemArchitecture.md
- API.md
- Security.md
---
# 1. Purpose
The Dashboard is the visual interface for MemOS. It provides visualization and debugging capabilities for the Memory Kernel (SRS 13.7).
The Dashboard is **not** a management plane for the kernel's intelligence.
It cannot
- calculate importance
- perform retrieval
- create versions
- decide permissions
These responsibilities remain inside the Memory Kernel (SRS 13.7).
---
# 2. Design Principles
The Dashboard shall be
- Readable
- Responsive
- Local-first
- Debug-friendly
- Kernel-safe
The Dashboard is a client of the REST API and contains **no business logic**.
It never accesses storage directly (PRD 17.5).
Dashboard interactions shall remain responsive and must not block the Memory Engine (NFR-006).
---
# 3. Architecture
```
Dashboard (React + TypeScript)
↓
REST API (/api/v1)
↓
Memory Kernel
↓
Core Services
```
The Dashboard is simply another API client (PRD 15).
---
# 4. Modules
Version 1 exposes the following modules (SRS 13.7).
| Module | Purpose |
|--------|---------|
| Statistics | Aggregate counts and health overview |
| Memory Explorer | View, edit metadata, archive, and delete memories |
| Search | Hybrid retrieval inspection |
| Graph Viewer | Visualize relationships between memories |
| Relationship Viewer | Inspect connections of a single memory |
| Version History | Inspect memory versions |
| Configuration | Display safe runtime configuration |
| Logs | Inspect the kernel audit log |
---
# 5. Responsibilities
The Dashboard shall
- View memories (FR-014)
- Search memories
- Inspect retrieval results and explanation metadata
- Inspect relationships (FR-015)
- Inspect version history (FR-016)
- Edit memory metadata (FR-017)
- Archive and delete memories (FR-018)
- Display system statistics
- Display safe configuration
- Display audit logs
The Dashboard shall **not**
- compute importance
- run retrieval algorithms
- create versions
- enforce permissions
(SRS 13.7)
---
# 6. API Surface
The Dashboard consumes the standard REST API (API.md) under the base URL `/api/v1`.
## System endpoints
```
GET /dashboard/statistics
GET /dashboard/health
GET /dashboard/logs
```
Used exclusively by the Dashboard (API.md 9).
## Shared endpoints used by the Dashboard
| Purpose | Endpoint |
|---------|----------|
| Create memory | POST /memories |
| Get memory | GET /memories/{memory_id} |
| Update memory | PUT /memories/{memory_id} |
| Delete memory | DELETE /memories/{memory_id} |
| Archive memory | PUT /memories/{memory_id}/archive |
| Restore memory | PUT /memories/{memory_id}/restore |
| List memories | GET /memories |
| Hybrid search | POST /search |
| List versions | GET /versions/{memory_id} |
| Get version | GET /versions/{memory_id}/{version} |
| Create relationship | POST /relationships |
| Delete relationship | DELETE /relationships/{relationship_id} |
| Get related memories | GET /relationships/{memory_id} |
| Safe configuration | GET /config |
---
# 7. Data Contracts
Every REST response uses the documented envelope (API.md 4).
## Statistics
```
GET /dashboard/statistics
```
Returns
- memory_count
- relationship_count
- audit_count
## Health
```
GET /dashboard/health
```
Returns
- status
- app
- version
- storage_backend
- embedding_backend
- kernel status
- metadata_store status
## Logs
```
GET /dashboard/logs
```
Supports filters
- operation
- result
- limit (1-500, default 100)
- offset
Returns
- records (audit log entries)
- total
Unknown filter values produce `INVALID_REQUEST`.
---
# 8. Configuration
The Dashboard displays safe runtime configuration via `GET /config`.
The Dashboard never displays
- database paths
- data directories
- credentials
(API.md 10, Security.md)
---
# 9. Security
The Dashboard assumes a trusted local environment.
- All permission decisions remain in the Memory Kernel.
- The Dashboard presents kernel decisions, including `PERMISSION_DENIED` errors, to the user.
- The Dashboard may send an acting principal via `X-Principal-ID` for local debugging.
---
# 10. Non-Functional Requirements
- Dashboard interactions must remain responsive (NFR-006).
- The Dashboard must render a degraded state when the kernel is unavailable.
- The Dashboard must never mutate memory outside the documented endpoints.
---
# 11. Repository Layout
```
dashboard/
    src/
        api/        # typed API client
        components/ # reusable UI components
        modules/    # one module per section 4
        App.tsx
        main.tsx
    index.html
    package.json
    vite.config.ts
    tsconfig.json
```
---
# 12. Conclusion
The Dashboard provides a human-readable window into MemOS while preserving the architecture's central rule: all intelligence and authority stay in the Memory Kernel.
