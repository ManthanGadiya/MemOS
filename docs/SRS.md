# Software Requirements Specification (SRS)
**Project Name:** MemOS (Memory Operating System)
**Version:** 0.1
**Status:** Draft
**Document Type:** Software Requirements Specification
**Target Release:** Version 1.0
**Related Documents**
- PRD.md
- Architecture.md
- Database.md
- API.md
- MemoryTheory.md
---
# Table of Contents
1. Introduction
2. Purpose
3. Scope
4. Definitions
5. System Context
6. Architectural Overview
7. Core Design Principles
8. System Components
9. Memory Kernel
10. Memory Object Specification
11. Memory Lifecycle
12. Functional Requirements
13. Non-Functional Requirements
14. External Interfaces
15. Error Handling
16. Validation Rules
17. Security
18. Testing Requirements
19. Traceability
---
# 1. Introduction
This document defines the complete software specification for MemOS.
Unlike the Product Requirements Document, which focuses on product vision and user needs, this Software Requirements Specification formally defines how MemOS shall behave from an engineering perspective.
The purpose of this document is to remove ambiguity before implementation begins.
Every subsystem, API, storage layer, retrieval algorithm, dashboard component, and future extension should derive its behavior from this specification.
Whenever implementation conflicts with documentation, this document becomes the primary engineering reference.
---
# 2. Purpose
MemOS exists to provide a standardized operating system responsible for managing the complete lifecycle of memories used by artificial intelligence systems.
Instead of embedding memory directly into language models or agent frameworks, MemOS exposes memory as an independent operating layer.
The system shall provide
- structured memory representation
- memory creation
- memory retrieval
- memory evolution
- version history
- permission management
- relationship management
- hybrid retrieval
- explainable decisions
without requiring any specific language model.
---
# 3. Scope
Version 1 includes
• Memory Kernel
• Memory Object
• Working Memory
• Semantic Memory
• Episodic Memory
• Version Engine
• Graph Engine
• Retrieval Engine
• Importance Engine
• Permission Engine
• REST API
• MCP Server
• Dashboard
Version 1 excludes
• Reflection Engine
• AI Summarization
• Multi User
• Distributed Storage
• Cloud Synchronization
• Background Consolidation
• Procedural Memory
• Emotional Memory
---
# 4. Definitions
## Memory
A unit of structured knowledge managed by MemOS.
A memory is not plain text.
It is an object possessing
- identity
- metadata
- relationships
- confidence
- importance
- lifecycle
- permissions
- versions
---
## Memory Object
The smallest manageable entity inside MemOS.
Every operation performed by the operating system targets one or more Memory Objects.
Memory Objects are immutable records representing a snapshot of knowledge at a specific point in time.
(Logical updates create new versions rather than modifying historical data.)
---
## Memory Kernel
The central subsystem responsible for coordinating every operation performed by MemOS.
No component communicates directly with storage.
All requests pass through the Memory Kernel.
---
## Memory Engine
Responsible for creating, updating, deleting, validating, and indexing Memory Objects.
---
## Retrieval Engine
Responsible for selecting memories relevant to an incoming query.
---
## Graph Engine
Responsible for managing relationships among Memory Objects.
---
## Importance Engine
Responsible for computing the relative significance of memories.
---
## Version Engine
Responsible for maintaining historical versions.
---
## Permission Engine
Responsible for validating access rights.
---
# 5. System Context
The Memory Operating System exists between AI applications and storage infrastructure.
```
```
                AI Application
                       │
                       │
                REST / MCP API
                       │
                       ▼
                Memory Kernel
                       │
     ┌─────────────────┼──────────────────┐
     │                 │                  │
 Memory Engine   Retrieval Engine   Graph Engine
     │                 │                  │
     └─────────────────┼──────────────────┘
                       │
              Importance Engine
                       │
               Permission Engine
                       │
                 Version Engine
                       │
                       ▼
                Storage Abstraction
          ┌────────────┼─────────────┐
          │            │             │
     Relational     Vector DB     Graph DB
      Database
```
Every interaction with MemOS begins at the Memory Kernel.
Subsystems never communicate directly with applications.
Applications never communicate directly with storage.
This separation guarantees
- consistency
- auditability
- extensibility
- storage independence
---
# 6. Architectural Overview
MemOS follows a layered architecture.
```
Presentation Layer
↓
API Layer
↓
Memory Kernel
↓
Core Engines
↓
Storage Layer
↓
Persistence
```
Each layer possesses a clearly defined responsibility.
Communication across layers occurs only through public interfaces.
Internal implementation details shall remain hidden.
---
## Layer Responsibilities
### Presentation Layer
Responsible for
- Dashboard
- SDK
- CLI (future)
---
### API Layer
Responsible for
- REST Endpoints
- MCP Server
- Authentication (future)
---
### Memory Kernel
Responsible for
- request routing
- validation
- transactions
- lifecycle management
- event generation
The Memory Kernel owns every memory operation.
---
### Core Engines
Responsible for
individual memory operations.
Examples
Memory Engine
Graph Engine
Version Engine
Importance Engine
Retrieval Engine
Permission Engine
---
### Storage Layer
Provides abstract interfaces.
Examples
```
Create()
Update()
Delete()
Query()
VectorSearch()
GraphTraversal()
```
Concrete implementations are hidden behind adapters.
---
# 7. Core Design Principles
Every subsystem shall satisfy the following principles.
---
## Principle 1
Single Responsibility
Each subsystem performs one responsibility.
Example
Graph Engine never computes importance.
Importance Engine never performs storage.
---
## Principle 2
Storage Independence
The kernel never depends upon
SQLite
Neo4j
FAISS
PostgreSQL
directly.
Instead
```
Kernel
↓
Storage Interface
↓
Adapter
↓
Implementation
```
---
## Principle 3
Deterministic Execution
Version 1 shall never require an LLM.
The same input must always produce the same output.
---
## Principle 4
Explainability
Every important decision made by MemOS shall expose reasoning metadata.
Examples
Importance score
Similarity score
Confidence score
Retrieval pathway
Relationship path
Version history
---
## Principle 5
Extensibility
Replacing
Graph Engine
Importance Engine
Retrieval Engine
should require minimal modifications to the remainder of the system.
---
# 8. System Components
Version 1 consists of the following primary components.
```
Memory Kernel
Memory Engine
Retrieval Engine
Graph Engine
Importance Engine
Permission Engine
Version Engine
Storage Manager
REST API
MCP Server
Dashboard
```
Each component exposes only public interfaces.
No component may manipulate another component's internal state directly.
Instead
```
Engine A
↓
Kernel
↓
Engine B
```
The Memory Kernel becomes the orchestrator of the entire operating system.
---
# 9. Memory Kernel
The Memory Kernel is the heart of MemOS.
Every request flows through it.
The kernel is responsible for
- request validation
- transaction management
- routing
- lifecycle transitions
- event emission
- logging
- coordination
- rollback
- permission checks
The kernel owns the lifecycle of every Memory Object.
---
## Kernel Responsibilities
### Receive Requests
Example
```
Create Memory
Retrieve Memory
Update Memory
Delete Memory
Search Memory
Link Memory
```
---
### Validate
The kernel validates
- schema
- permissions
- object integrity
- duplicate identifiers
- lifecycle state
before forwarding the request.
---
### Route
The kernel routes work to
Memory Engine
Graph Engine
Version Engine
Importance Engine
without exposing implementation details.
---
### Coordinate
Suppose memory update requires
Version Engine
+
Graph Engine
+
Storage
The kernel coordinates the complete transaction.
If any stage fails,
the entire operation rolls back.
---
### Emit Events
Future versions may subscribe to kernel events.
Examples
```
MemoryCreated
MemoryUpdated
MemoryDeleted
MemoryRetrieved
RelationshipAdded
RelationshipRemoved
```
Version 1 records events for logging purposes only.
---
### Kernel Rules
KR-001
No subsystem may bypass the Memory Kernel.
---
KR-002
Every write operation shall execute inside a transaction.
---
KR-003
The kernel shall reject invalid lifecycle transitions.
---
KR-004
Every operation shall produce an audit log.
---
KR-005
Kernel interfaces shall remain stable across minor releases.
---
---
# 10. Memory Object Specification
## 10.1 Overview
The Memory Object is the fundamental data structure managed by MemOS.
Every subsystem inside MemOS operates on Memory Objects.
The Memory Object is analogous to an inode in a traditional operating system.
Applications never manipulate storage directly.
Instead, applications request operations on Memory Objects through the Memory Kernel.
Every Memory Object represents exactly one logical piece of information.
Examples include
- a user preference
- an event
- a project milestone
- a deadline
- a factual statement
The Memory Object remains implementation-independent.
Whether the data is stored in PostgreSQL, SQLite, Neo4j, or another storage engine is irrelevant to the kernel.
---
# 10.2 Memory Object Goals
The Memory Object shall
- uniquely identify every memory
- support version history
- maintain relationships
- store metadata
- support indexing
- support retrieval
- support permissions
- remain storage independent
- remain serialization independent
---
# 10.3 Canonical Structure
Every Memory Object shall contain the following sections.
```
Memory Object
├── Header
├── Identity
├── Classification
├── Content
├── Metadata
├── Importance
├── Confidence
├── Relationships
├── Version Information
├── Permissions
├── Embedding
├── Retrieval Metadata
├── Lifecycle Metadata
└── Audit Metadata
```
No section may be omitted unless explicitly stated as optional.
---
# 10.4 Memory Header
The Header contains system-level information.
| Field | Required | Description |
|--------|----------|-------------|
| schema_version | Yes | Memory schema version |
| object_type | Yes | Must always be "memory" |
| serialization | Yes | Serialization format |
| checksum | Optional | Integrity verification |
Example
```json
{
    "schema_version": "1.0",
    "object_type": "memory",
    "serialization": "json"
}
```
---
# 10.5 Identity
Every Memory Object shall possess a globally unique identifier.
Fields
| Field | Required |
|--------|----------|
| memory_id | Yes |
| namespace | Yes |
| owner_id | Yes |
Description
memory_id
Unique immutable identifier.
Never changes.
namespace
Logical grouping.
Examples
```
personal
project
system
shared
```
owner_id
Owner of the memory.
Version 1 supports only one owner.
---
# 10.6 Classification
Classification determines how the kernel processes the memory.
Fields
| Field | Required |
|--------|----------|
| memory_type | Yes |
| category | Yes |
| tags | Optional |
Version 1 memory types
```
WORKING
SEMANTIC
EPISODIC
```
Examples
Semantic
```
User prefers Python
```
Episodic
```
Created Project Alpha
```
Working
```
Current task
```
---
# 10.7 Content
Content stores the actual information represented by the Memory Object.
Fields
| Field | Required |
|--------|----------|
| title | Yes |
| content | Yes |
| summary | No |
| source | Yes |
Example
```
Title
Preferred Language
Content
User prefers Python for backend development.
Source
Conversation
```
Content remains immutable.
Logical updates create new versions.
---
# 10.8 Metadata
Metadata stores contextual information.
Fields
| Field | Required |
|--------|----------|
| created_at | Yes |
| updated_at | Yes |
| created_by | Yes |
| updated_by | Yes |
| expires_at | No |
| timezone | No |
| locale | No |
Metadata never influences logical meaning.
It exists only to provide context.
---
# 10.9 Importance
Every memory possesses an importance score.
Purpose
Determine
- retrieval priority
- decay
- ranking
Fields
| Field | Required |
|--------|----------|
| score | Yes |
| last_calculated | Yes |
| calculation_method | Yes |
Version 1
```
Range
0–100
```
Interpretation
```
0–20
Very Low
21–40
Low
41–60
Medium
61–80
High
81–100
Critical
```
The exact scoring algorithm is defined in Algorithms.md.
---
# 10.10 Confidence
Confidence estimates correctness.
Fields
| Field | Required |
|--------|----------|
| confidence | Yes |
| confidence_source | Yes |
| confidence_last_updated | Yes |
Range
```
0.0
↓
1.0
```
Interpretation
```
1.0
Verified
```
```
0.8
Highly Likely
```
```
0.5
Uncertain
```
```
0.2
Weak
```
Confidence is independent of importance.
---
Example
```
User likes Python
Confidence
0.95
Importance
92
```
versus
```
Today's weather
Confidence
1.0
Importance
4
```
---
# 10.11 Relationships
Relationships connect Memory Objects.
Each relationship contains
| Field | Required |
|--------|----------|
| relationship_id | Yes |
| source_memory | Yes |
| target_memory | Yes |
| relationship_type | Yes |
| weight | Yes |
Relationship Types
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
Multiple relationships are allowed.
Circular relationships are prohibited unless explicitly permitted.
---
# 10.12 Version Information
Every logical update creates a new version.
Fields
| Field | Required |
|--------|----------|
| version | Yes |
| previous_version | No |
| latest_version | Yes |
| change_reason | Yes |
Version numbering
```
1
↓
2
↓
3
↓
4
```
Historical versions remain immutable.
Only the latest version is active.
---
# 10.13 Permissions
Every Memory Object possesses access rules.
Fields
| Field | Required |
|--------|----------|
| visibility | Yes |
| owner | Yes |
| editable | Yes |
| deletable | Yes |
| exportable | Yes |
Version 1 visibility
```
PRIVATE
SYSTEM
```
Future versions may include
```
PUBLIC
TEAM
ORGANIZATION
```
---
# 10.14 Embedding
Semantic retrieval requires vector embeddings.
Fields
| Field | Required |
|--------|----------|
| embedding_id | Yes |
| embedding_model | Yes |
| dimensions | Yes |
| embedding_version | Yes |
Embeddings are stored separately from content.
The Memory Object stores only references.
---
# 10.15 Retrieval Metadata
Stores information generated during retrieval.
Fields
| Field | Required |
|--------|----------|
| retrieval_count | Yes |
| last_retrieved | No |
| average_rank | No |
These fields assist future ranking algorithms.
Version 1 does not modify retrieval behavior using these values.
---
# 10.16 Lifecycle Metadata
Current lifecycle state.
Possible values
```
CREATED
VALIDATED
INDEXED
ACTIVE
ARCHIVED
DELETED
```
Illegal transitions shall be rejected by the Memory Kernel.
---
# 10.17 Audit Metadata
Every modification is recorded.
Fields
| Field | Required |
|--------|----------|
| created_by | Yes |
| modified_by | Yes |
| modified_at | Yes |
| operation | Yes |
Example
```
Operation
UPDATE
Time
2026-08-05T18:10Z
User
Agent001
```
---
# 10.18 Memory Object Invariants
The following conditions shall always remain true.
MO-001
Every Memory Object possesses exactly one immutable identifier.
---
MO-002
Every Memory Object belongs to exactly one owner.
---
MO-003
Historical versions are immutable.
---
MO-004
The active version shall always be the latest version.
---
MO-005
Relationships reference valid Memory Objects.
---
MO-006
Importance shall remain within
```
0 ≤ score ≤ 100
```
---
MO-007
Confidence shall remain within
```
0 ≤ confidence ≤ 1
```
---
MO-008
Memory type cannot change after creation.
---
MO-009
Deleted memories shall never participate in retrieval.
---
MO-010
Every Memory Object shall possess lifecycle metadata.
---
# 10.19 Memory Object Lifecycle
```
Create
↓
Validate
↓
Assign ID
↓
Store Metadata
↓
Generate Embedding
↓
Create Index
↓
Graph Linking
↓
ACTIVE
↓
Retrieve
↓
Update
↓
Create New Version
↓
Archive
↓
Delete
```
---
# 10.20 Memory Object Validation
Before a Memory Object is accepted, the kernel shall verify
✓ Required fields exist
✓ Identifier uniqueness
✓ Valid owner
✓ Valid memory type
✓ Valid lifecycle state
✓ Valid confidence range
✓ Valid importance range
✓ Valid relationship references
✓ Valid permissions
✓ Valid schema version
Failure of any validation shall reject the operation.
---
```
---
# 11. Memory Lifecycle Specification
## 11.1 Overview
The Memory Lifecycle defines every state through which a Memory Object progresses during its existence.
Unlike conventional databases where a record is simply created, updated, and deleted, MemOS treats memories as living entities with well-defined lifecycle states.
Every Memory Object shall always exist in exactly one lifecycle state.
Lifecycle transitions are managed exclusively by the Memory Kernel.
Subsystems are prohibited from modifying lifecycle states directly.
---
# 11.2 Objectives
The Memory Lifecycle is designed to provide
- deterministic behavior
- predictable state transitions
- auditability
- version consistency
- retrieval consistency
- storage integrity
---
# 11.3 Lifecycle States
Version 1 defines the following lifecycle states.
```
CREATED
↓
VALIDATED
↓
INDEXED
↓
ACTIVE
↓
UPDATED
↓
ARCHIVED
↓
DELETED
```
Every Memory Object must follow this sequence unless explicitly specified otherwise.
---
# 11.4 State Definitions
## CREATED
Description
The Memory Object has been received by the Memory Kernel and assigned an identifier.
Characteristics
- identifier assigned
- schema validated
- storage not yet completed
- embedding not generated
- unavailable for retrieval
Allowed Operations
✓ Validate
✓ Reject
Forbidden Operations
✗ Retrieve
✗ Update
✗ Link
---
## VALIDATED
Description
The Memory Object has passed schema validation.
Characteristics
- required fields verified
- identifier uniqueness verified
- ownership verified
- lifecycle initialized
Allowed Operations
✓ Store
✓ Generate Embedding
✓ Create Relationships
Forbidden Operations
✗ Retrieve
---
## INDEXED
Description
Storage has completed successfully.
Embedding generation and indexing have finished.
Characteristics
- relational storage complete
- vector index updated
- graph nodes created
Allowed Operations
✓ Activate
Forbidden Operations
✗ Delete without activation
---
## ACTIVE
Description
The memory is available to the retrieval engine.
Characteristics
- searchable
- retrievable
- editable
- linkable
Allowed Operations
✓ Retrieve
✓ Update
✓ Archive
✓ Delete
✓ Link
---
## UPDATED
Description
The logical memory has changed.
A new version has been created.
Characteristics
- previous version preserved
- latest version active
- history maintained
The UPDATED state is transitional.
The object automatically returns to ACTIVE after successful version creation.
---
## ARCHIVED
Description
The memory is no longer considered active but remains stored.
Characteristics
- retrievable by explicit request
- excluded from default retrieval
- immutable
Use Cases
- completed projects
- expired deadlines
- inactive preferences
---
## DELETED
Description
The memory has been permanently removed from active storage.
Characteristics
- excluded from retrieval
- relationships removed
- immutable
Version 1 performs logical deletion.
Physical deletion may occur later.
---
# 11.5 State Transition Rules
Allowed transitions
```
CREATED
↓
VALIDATED
↓
INDEXED
↓
ACTIVE
↓
UPDATED
↓
ACTIVE
↓
ARCHIVED
↓
DELETED
```
Illegal transitions
```
CREATED
↓
ACTIVE
```
Reason
Validation skipped.
---
```
VALIDATED
↓
ARCHIVED
```
Reason
Never activated.
---
```
DELETED
↓
ACTIVE
```
Reason
Deleted memories cannot be reactivated.
---
```
ARCHIVED
↓
CREATED
```
Reason
Lifecycle cannot restart.
---
# 11.6 Lifecycle State Machine
```
                 +-----------+
                 | CREATED   |
                 +-----------+
                       |
                       v
                 +-----------+
                 |VALIDATED  |
                 +-----------+
                       |
                       v
                 +-----------+
                 | INDEXED   |
                 +-----------+
                       |
                       v
                 +-----------+
                 | ACTIVE    |
                 +-----------+
                   |    |
          Update   |    | Archive
                   |    |
                   v    v
            +-----------+      +------------+
            | UPDATED   | ---> | ARCHIVED   |
            +-----------+      +------------+
                   |
                   |
                   v
              +-----------+
              | ACTIVE    |
              +-----------+
ARCHIVED
    |
Delete
    |
    v
+-----------+
| DELETED  |
+-----------+
```
---
# 11.7 Lifecycle Validation Rules
LC-001
A Memory Object shall never exist without a lifecycle state.
---
LC-002
The Memory Kernel shall reject illegal transitions.
---
LC-003
Every lifecycle transition shall generate an audit event.
---
LC-004
Deleted memories shall never participate in retrieval.
---
LC-005
Archived memories shall not appear in default search results.
---
LC-006
Only ACTIVE memories may receive updates.
---
LC-007
Only ACTIVE memories may create relationships.
---
LC-008
Historical versions shall preserve their original lifecycle metadata.
---
# 11.8 Lifecycle Events
Every transition generates an event.
Example
```
MemoryCreated
MemoryValidated
MemoryIndexed
MemoryActivated
MemoryUpdated
MemoryArchived
MemoryDeleted
```
Version 1 records events only.
Future versions may expose event subscriptions.
---
# 11.9 Failure Handling
If any lifecycle operation fails
the Memory Kernel shall
1.
Abort the transaction.
2.
Rollback partial changes.
3.
Restore previous lifecycle state.
4.
Generate an audit record.
5.
Return an error.
Lifecycle consistency is considered more important than partial completion.
---
# 12. Functional Requirements
The following functional requirements define the expected behavior of MemOS Version 1.
Every requirement in this section is testable.
Each requirement shall receive corresponding implementation tests.
---
# 12.1 Memory Creation
FR-001
The system shall create a Memory Object.
---
FR-002
Every created memory shall receive a globally unique identifier.
---
FR-003
The Memory Kernel shall validate every Memory Object before storage.
---
FR-004
Memory creation shall fail if mandatory fields are missing.
---
FR-005
Memory creation shall fail if validation fails.
---
FR-006
Successful creation shall trigger embedding generation.
---
FR-007
Successful creation shall update graph storage.
---
FR-008
Successful creation shall create audit records.
---
# 12.2 Memory Retrieval
FR-009
The system shall retrieve memories using identifiers.
---
FR-010
The system shall retrieve memories using semantic similarity.
---
FR-011
The system shall retrieve memories using metadata filters.
---
FR-012
The system shall retrieve memories using graph traversal.
---
FR-013
The system shall combine multiple retrieval strategies.
---
FR-014
Retrieved memories shall include explanation metadata.
---
FR-015
Deleted memories shall never be returned.
---
FR-016
Archived memories shall only appear when explicitly requested.
---
# 12.3 Memory Updates
FR-017
Updates shall never overwrite historical versions.
---
FR-018
Updates shall create new versions.
---
FR-019
Previous versions shall remain immutable.
---
FR-020
Relationship integrity shall remain valid after updates.
---
FR-021
Embedding regeneration shall occur when memory content changes.
---
FR-022
Metadata-only changes shall not require embedding regeneration.
---
# 12.4 Memory Deletion
FR-023
Deletion shall require permission validation.
---
FR-024
Deleted memories shall be marked as DELETED.
---
FR-025
Deleted memories shall not participate in retrieval.
---
FR-026
Deletion shall preserve audit history.
---
# 12.5 Relationship Management
FR-027
The system shall support relationship creation.
---
FR-028
The system shall support relationship deletion.
---
FR-029
Relationship types shall be validated.
---
FR-030
Relationship references shall point to existing Memory Objects.
---
FR-031
Circular relationships shall be rejected unless explicitly permitted.
---
# 12.6 Version Management
FR-032
Every logical update shall create a new version.
---
FR-033
Version numbers shall increase monotonically.
---
FR-034
Historical versions shall remain immutable.
---
FR-035
The latest version shall always be active.
---
FR-036
Every version shall maintain its own metadata.
---
# 12.7 Permission Management
FR-037
Every request shall pass through permission validation.
---
FR-038
Unauthorized operations shall fail.
---
FR-039
Permission checks shall occur before retrieval.
---
FR-040
Permission rules shall remain independent of storage implementation.
---
# 12.8 Kernel Requirements
FR-041
Every request shall pass through the Memory Kernel.
---
FR-042
Subsystems shall never bypass the Kernel.
---
FR-043
Kernel operations shall be transactional.
---
FR-044
Kernel failures shall rollback incomplete operations.
---
FR-045
Every operation shall generate audit logs.
---
FR-046
Kernel interfaces shall remain stable throughout Version 1.
---
---
# 13. External Interfaces
## 13.1 Overview
MemOS exposes all functionality through well-defined interfaces.
No application shall communicate directly with storage engines.
Every interaction shall occur through one of the supported interfaces.
Version 1 provides
- REST API
- MCP Server
- Python SDK
- Web Dashboard
Future interfaces may include
- CLI
- gRPC
- WebSocket
- JavaScript SDK
- Go SDK
- Rust SDK
---
# 13.2 Interface Architecture
```
               Applications
    AI Agent      Dashboard      SDK
          │           │           │
          └───────────┼───────────┘
                      │
             Public Interfaces
        REST API      MCP Server
                      │
                Memory Kernel
                      │
              Internal Engines
                      │
              Storage Adapters
                      │
      PostgreSQL   Neo4j   Vector DB
```
Applications shall never access storage directly.
Applications shall never invoke internal engines directly.
The Memory Kernel remains the single entry point into the operating system.
---
# 13.3 REST API Requirements
The REST API is the primary communication interface.
All endpoints shall return JSON.
All requests shall be stateless.
Every response shall include
- request identifier
- timestamp
- status
- execution duration
---
## Memory Endpoints
The API shall support
```
POST
/memories
```
Create Memory
---
```
GET
/memories/{id}
```
Retrieve Memory
---
```
PUT
/memories/{id}
```
Update Memory
---
```
DELETE
/memories/{id}
```
Delete Memory
---
```
GET
/memories
```
List Memories
---
```
POST
/search
```
Hybrid Retrieval
---
```
POST
/graph/link
```
Create Relationship
---
```
DELETE
/graph/link
```
Remove Relationship
---
```
GET
/versions/{memory_id}
```
Retrieve Version History
---
```
GET
/dashboard/statistics
```
System Statistics
---
# 13.4 REST Response Format
Every successful response shall follow the same schema.
Example
```json
{
  "success": true,
  "request_id": "...",
  "timestamp": "...",
  "data": {},
  "metadata": {}
}
```
Every error response shall follow
```json
{
  "success": false,
  "error": {
      "code": "...",
      "message": "...",
      "details": {}
  }
}
```
Consistent response structures simplify SDK development.
---
# 13.5 MCP Interface
Version 1 shall expose MemOS as an MCP Server.
The MCP Server provides AI agents with standardized access to memory operations.
Supported tools include
```
create_memory
retrieve_memory
update_memory
delete_memory
search_memory
link_memory
list_versions
get_memory
archive_memory
```
Every MCP tool shall internally invoke the Memory Kernel.
No MCP tool may bypass kernel validation.
---
# 13.6 Python SDK
Version 1 provides an official Python SDK.
The SDK is a thin wrapper around the REST API.
Example
```python
client.create_memory()
client.retrieve_memory()
client.search()
client.update()
client.delete()
client.link()
client.archive()
```
The SDK shall never implement business logic.
Business logic remains inside the Memory Kernel.
---
# 13.7 Dashboard
The Dashboard provides visualization and debugging capabilities.
Version 1 dashboard modules
Memory Explorer
Graph Viewer
Version History
Relationship Viewer
Statistics
Search
Configuration
Logs
---
Dashboard responsibilities
View memories
Search memories
Inspect retrieval
Inspect relationships
Inspect versions
Delete memories
Archive memories
Edit metadata
---
The dashboard is not responsible for
importance calculation
retrieval
versioning
permission logic
These responsibilities remain inside the Memory Kernel.
---
# 14. Error Handling
## 14.1 Objectives
Every failure inside MemOS shall be
- deterministic
- recoverable when possible
- logged
- understandable
Errors shall never leave the system in an inconsistent state.
---
# 14.2 Error Categories
Version 1 defines the following error classes.
Validation Errors
Permission Errors
Retrieval Errors
Storage Errors
Graph Errors
Version Errors
Kernel Errors
Internal Errors
Configuration Errors
---
## Validation Errors
Examples
Missing fields
Invalid schema
Duplicate identifier
Invalid confidence
Invalid importance
Response
HTTP 400
---
## Permission Errors
Examples
Unauthorized retrieval
Unauthorized update
Unauthorized deletion
Response
HTTP 403
---
## Retrieval Errors
Examples
Memory not found
Embedding unavailable
Relationship missing
Response
HTTP 404
---
## Storage Errors
Examples
Database unavailable
Vector database unavailable
Graph database unavailable
Response
HTTP 500
---
## Kernel Errors
Examples
Transaction failure
Rollback failure
Lifecycle violation
Response
HTTP 500
---
# 14.3 Error Codes
Every error shall possess
Code
Category
Description
Suggested Action
Example
```
MEMORY_NOT_FOUND
Category
Retrieval
Action
Verify identifier.
```
---
# 14.4 Transaction Failures
If any operation fails
the Memory Kernel shall
Abort
Rollback
Log
Return Error
No partial operation shall remain committed.
---
# 14.5 Logging
Every error shall generate
Timestamp
Request ID
Memory ID (if available)
Operation
Subsystem
Stack Trace
Severity
Logs shall remain immutable.
---
# 15. Validation Rules
Every Memory Object shall satisfy validation before storage.
---
## Required Field Validation
The following fields are mandatory.
Memory Identifier
Memory Type
Title
Content
Owner
Created Timestamp
Importance
Confidence
Lifecycle State
Schema Version
Failure to provide mandatory fields shall reject the operation.
---
## Range Validation
Importance
```
0 ≤ importance ≤ 100
```
Confidence
```
0 ≤ confidence ≤ 1
```
Version
```
Version ≥ 1
```
---
## Relationship Validation
Every relationship shall reference
an existing Memory Object.
Relationships pointing to deleted objects are invalid.
---
## Lifecycle Validation
Illegal lifecycle transitions are rejected.
Example
```
CREATED
↓
ACTIVE
```
Invalid
---
```
ACTIVE
↓
VALIDATED
```
Invalid
---
## Version Validation
Latest version shall always possess the highest version number.
Historical versions cannot be modified.
---
## Permission Validation
Every operation shall verify
Owner
Visibility
Operation
before execution.
---
# 16. Security Requirements
Version 1 targets local deployment.
However, security principles shall be enforced from the beginning.
---
## SR-001
Every Memory Object shall possess ownership.
---
## SR-002
Permission validation shall occur before every operation.
---
## SR-003
Private memories shall never appear in unauthorized retrieval results.
---
## SR-004
Audit logs shall remain immutable.
---
## SR-005
Version history shall remain immutable.
---
## SR-006
Memory identifiers shall be globally unique.
---
## SR-007
Kernel transactions shall be atomic.
---
## SR-008
Sensitive configuration shall remain outside source code.
---
# 17. Testing Requirements
Every functional requirement defined in this document shall possess corresponding automated tests.
Version 1 testing strategy includes
Unit Tests
Integration Tests
API Tests
Storage Tests
Kernel Tests
Performance Tests
Regression Tests
---
## Unit Tests
Individual engines shall be tested independently.
Examples
Memory Engine
Graph Engine
Version Engine
Importance Engine
Permission Engine
---
## Integration Tests
Verify communication between
Kernel
↓
Engines
↓
Storage
---
## API Tests
Every REST endpoint shall be tested.
Success
Failure
Invalid Input
Permission Failure
Performance
---
## Performance Tests
Metrics
Memory Creation
Memory Retrieval
Search Latency
Graph Traversal
Version Creation
Dashboard Response
---
## Regression Tests
Previously fixed bugs shall never reappear.
Every bug fix shall include
- regression test
- documentation
- changelog entry
---
# 18. Requirements Traceability Matrix
The following matrix establishes traceability between the Product Requirements Document and implementation.
| PRD Goal | SRS Section |
|-----------|-------------|
| Persistent Memory | Memory Object |
| Memory Lifecycle | Lifecycle Specification |
| Hybrid Retrieval | Retrieval Requirements |
| Version History | Version Requirements |
| Graph Relationships | Relationship Requirements |
| REST API | External Interfaces |
| MCP Support | External Interfaces |
| Dashboard | Dashboard Requirements |
| Permissions | Security Requirements |
| Explainability | Retrieval Metadata |
Every implementation task shall trace back to at least one requirement defined in this document.
---
# 19. Conclusion
This Software Requirements Specification defines the complete engineering contract for MemOS Version 1.
The architecture described herein establishes the Memory Kernel as the central authority responsible for all memory operations, while supporting modular engines, storage abstraction, and deterministic execution.
Future documents—including the Architecture Specification, Database Design, API Specification, Algorithms, and implementation roadmap—shall build upon the requirements and interfaces defined in this specification.
No implementation shall contradict this document without an approved Architecture Decision Record (ADR).
---