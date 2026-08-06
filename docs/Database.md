# Database Specification
**Project:** MemOS (Memory Operating System)
**Document Version:** 1.0
**Status:** Draft
**Related Documents**
- PRD.md
- SRS.md
- MemoryTheory.md
- SystemArchitecture.md
- Algorithms.md
- API.md
---
# 1. Purpose
This document defines the database architecture of MemOS.
The database layer is responsible only for **persisting representations of Memory Objects**.
It is **not** responsible for
- retrieval logic
- importance calculation
- permission validation
- lifecycle management
- version management
Those responsibilities belong to the Memory Kernel and Core Services.
---
# 2. Database Philosophy
MemOS separates **memory** from **storage**.
```
Memory Object
↓
Storage Abstraction
↓
Database
```
Changing the database must never change the behavior of MemOS.
---
# 3. Storage Architecture
Version 1 uses three specialized storage systems.
```
                Memory Kernel
                      │
        ┌─────────────┼─────────────┐
        │             │             │
 Metadata DB     Vector DB     Graph DB
```
Each database has one responsibility.
| Database | Responsibility |
|-----------|---------------|
| Metadata DB | Source of truth for Memory Objects |
| Vector DB | Semantic similarity search |
| Graph DB | Relationships between Memory Objects |
---
# 4. Metadata Database
Recommended
- SQLite (Development)
- PostgreSQL (Production)
Stores
- Memory Objects
- Versions
- Metadata
- Lifecycle
- Permissions
- Audit Logs
Example tables
```
memories
memory_versions
permissions
audit_logs
users (future)
```
The Metadata Database is the **authoritative source of truth**.
---
# 5. Vector Database
Recommended
- Qdrant
- FAISS (local)
Stores
- Embeddings
- Embedding metadata
- Vector index
Does **not** store
- permissions
- lifecycle
- versions
- relationships
Only returns candidate Memory IDs.
---
# 6. Graph Database
Recommended
- Neo4j
Stores
- Nodes
- Relationships
- Relationship types
- Relationship weights
Supported relationships
```
RELATED_TO
BELONGS_TO
DEPENDS_ON
PARENT_OF
CHILD_OF
SUPERSEDES
CONTRADICTS
REFERENCES
FOLLOW_UP
```
---
# 7. Memory Object Schema
Every Memory Object contains
```
Memory ID
Memory Type
Title
Content
Metadata
Importance
Confidence
Version
Lifecycle
Owner
Tags
```
Embeddings and graph relationships are stored separately.
---
# 8. Versioning
MemOS never overwrites memories.
Instead
```
Version 1
↓
Version 2
↓
Version 3
```
Only the latest version is active.
Historical versions remain immutable.
---
# 9. Relationships
Relationships are stored in the Graph Database.
Each relationship contains
```
Relationship ID
Source Memory
Target Memory
Type
Weight
Created At
```
---
# 10. Indexing Strategy
Metadata DB
- Primary Key Index
- Owner Index
- Memory Type Index
- Lifecycle Index
- Created Time Index
Vector DB
- Embedding Index
Graph DB
- Node Index
- Relationship Index
Indexes exist only to improve query performance.
---
# 11. Transactions
Every write operation is coordinated by the Memory Kernel.
```
Begin Transaction
↓
Metadata Update
↓
Embedding Update
↓
Graph Update
↓
Commit
```
If any stage fails
```
Rollback
↓
Restore Previous State
```
---
# 12. Backup Strategy
Version 1 supports
- Metadata database backup
- Vector database snapshot
- Graph database export
Future versions may introduce automatic scheduled backups.
---
# 13. Scalability
Version 1 target
- Single User
- Local Deployment
- ~1,000 Memory Objects
The architecture allows future migration to distributed databases without changing the Memory Object abstraction.
---
# 14. Database Principles
1. Metadata is the source of truth.
2. Embeddings are representations, not memories.
3. Relationships are stored independently.
4. Historical versions are immutable.
5. Memory Objects never directly depend on database technologies.
6. All persistence occurs through Storage Adapters.
7. Every write operation is transactional.
---
# 15. Conclusion
The MemOS database architecture follows a **polyglot persistence** approach where different databases are used for different responsibilities.
- Relational databases store Memory Objects and metadata.
- Vector databases enable semantic retrieval.
- Graph databases manage relationships.
The Memory Kernel coordinates these storage systems through a storage abstraction layer, ensuring deterministic behavior, consistency, and portability while keeping the underlying database implementations interchangeable.
---