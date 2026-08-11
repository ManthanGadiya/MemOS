# MCP Specification
**Project:** MemOS (Memory Operating System)
**Document Version:** 1.0
**Status:** Draft
**Protocol:** Model Context Protocol (MCP)
**Related Documents**
- PRD.md
- SRS.md
- MemoryTheory.md
- SystemArchitecture.md
- API.md
---
# 1. Purpose
The MCP Server enables AI agents to interact with MemOS using the **Model Context Protocol (MCP)**.
Instead of calling REST APIs directly, compatible AI assistants and agents communicate through standardized MCP tools.
The MCP Server acts as a bridge between AI models and the Memory Kernel.
```
AI Agent
↓
MCP Client
↓
MCP Server
↓
Memory Kernel
↓
Core Services
```
The MCP Server contains **no business logic**.
It simply translates MCP requests into kernel operations.
---
# 2. Design Principles
The MCP Server shall be
- Stateless
- Model Agnostic
- Deterministic
- Tool-Based
- Secure
- Extensible
The MCP Server shall never access databases directly.
All operations pass through the Memory Kernel.
---
# 3. Architecture
```
AI Assistant
↓
MCP Client
↓
MemOS MCP Server
↓
Memory Kernel
↓
Core Services
↓
Storage
```
Multiple AI agents may communicate with the same MCP Server.
---
# 4. Supported MCP Tools
Version 1 exposes the following tools.
| Tool | Purpose |
|------|---------|
| create_memory | Create a Memory Object |
| get_memory | Retrieve a Memory Object |
| search_memory | Hybrid memory retrieval |
| update_memory | Create a new version |
| delete_memory | Delete a Memory Object |
| archive_memory | Archive a Memory Object |
| list_memories | List stored memories |
| list_versions | Retrieve version history |
| create_relationship | Link two memories |
| delete_relationship | Remove relationship |
| related_memories | Retrieve connected memories |
| system_health | Retrieve MemOS status |
---
# 5. Tool Descriptions
## create_memory
Creates a new Memory Object.
Input
- title
- content
- memory_type
- tags (optional)
Returns
- memory_id
- status
---
## get_memory
Returns a Memory Object by ID.
Input
- memory_id
Returns
- complete Memory Object
---
## search_memory
Performs hybrid retrieval.
Input
- query
- filters (optional)
Returns
- ranked Memory Objects
- explanation metadata
---
## update_memory
Creates a new version.
Input
- memory_id
- updated content
Returns
- latest version
---
## delete_memory
Marks a memory as deleted.
Input
- memory_id
Returns
- operation status
---
## archive_memory
Archives a Memory Object.
Input
- memory_id
Returns
- operation status
---
## list_memories
Returns all Memory Objects.
Supports filters
- type
- tags
- lifecycle
---
## list_versions
Returns version history.
Input
- memory_id
---
## create_relationship
Creates a graph relationship.
Input
- source_memory
- target_memory
- relationship_type
---
## delete_relationship
Deletes an existing relationship.
Input
- relationship_id
---
## related_memories
Returns connected memories.
Input
- memory_id
---
## system_health
Returns
- Kernel status
- Storage status
- MCP status
---
# 6. Tool Execution Flow
Every tool follows the same execution model.
```
Tool Request
↓
Input Validation
↓
Memory Kernel
↓
Core Service
↓
Response
↓
MCP Client
```
The MCP Server shall never execute memory operations independently.
---
# 7. Resources
Version 1 exposes read-only resources.
Examples
```
Memory Objects
Memory Versions
Relationships
System Statistics
Configuration
Health Status
```
Resources provide contextual information without modifying memory.
---
# 8. Error Handling
Every tool returns structured errors.
Common errors
| Error | Description |
|--------|-------------|
| INVALID_INPUT | Invalid request |
| MEMORY_NOT_FOUND | Unknown Memory Object |
| PERMISSION_DENIED | Unauthorized operation |
| STORAGE_FAILURE | Database unavailable |
| INTERNAL_ERROR | Unexpected failure |
---
# 9. Security
Version 1 assumes trusted local environments.
Future versions may support
- Authentication
- API Keys
- OAuth
- Agent Identity
- Tool Permissions
All authorization decisions remain inside the Memory Kernel.
---
# 10. Future Extensions
Future MCP capabilities may include
- Reflection Tool
- Memory Consolidation
- Batch Operations
- Streaming Retrieval
- Event Subscriptions
- Multi-Agent Collaboration
These extensions shall integrate without modifying existing tool contracts.
---
# 11. Design Principles
1. Every tool maps to a Memory Kernel operation.
2. The MCP Server contains no business logic.
3. Tool contracts remain stable across minor releases.
4. All responses are deterministic.
5. The MCP Server remains model agnostic.
6. Future tools shall preserve backward compatibility.
---
# 12. Conclusion
The MemOS MCP Server provides a standardized interface that allows any MCP-compatible AI assistant or autonomous agent to interact with the Memory Operating System.
By translating MCP tool invocations into Memory Kernel operations, it enables seamless integration while preserving MemOS's core principles of determinism, modularity, and model independence.
---