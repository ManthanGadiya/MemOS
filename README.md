# MemOS — Memory Operating System for AI

<div align="center">

**A Model-Agnostic Memory Operating System for AI Agents**

*Persistent • Explainable • Deterministic • Versioned • Hybrid Retrieval*

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)]()
[![Status](https://img.shields.io/badge/Status-Research%20Project-red.svg)]()

</div>

---
# What is MemOS?
Modern AI systems are incredibly intelligent, but they still suffer from one major limitation:
> **They don't truly remember.**

Today's "memory" solutions are usually combinations of

- Chat History
- Context Windows
- Vector Databases
- RAG
- Prompt Engineering

These improve context, but **they are not memory systems**.

MemOS aims to change that.

Instead of embedding memory inside every AI application, MemOS provides a dedicated **Memory Operating System** responsible for the complete lifecycle of AI memory.

Just as an Operating System manages hardware,

MemOS manages memory.

---

# Vision

Create the standard infrastructure layer for AI memory.

```
Applications

↓

AI Models

↓

MemOS

↓

Storage
```

Applications should no longer implement memory themselves.

Instead,

they communicate with MemOS.

---

# Core Philosophy

MemOS is built around several fundamental principles.

## Memory ≠ Storage

Databases store data.

MemOS manages memory.

---

## Memory ≠ Embeddings

Embeddings are one representation of memory.

They are not memory itself.

---

## Memory ≠ Knowledge

Knowledge emerges from connected memories.

Memory stores experiences and facts.

---

## Memory Objects are First-Class

Everything inside MemOS operates on **Memory Objects**.

Not strings.

Not JSON.

Not database rows.

---

## Memory Kernel

Every request passes through the Memory Kernel.

No component may bypass it.

The kernel owns

- validation
- routing
- lifecycle
- transactions
- rollback
- audit
- event generation

---

# Features

## Memory Types

- Working Memory
- Semantic Memory
- Episodic Memory

---

## Memory Lifecycle

- Create
- Validate
- Version
- Retrieve
- Archive
- Delete

---

## Hybrid Retrieval

Retrieval combines

- Metadata Filtering
- Vector Similarity
- Graph Traversal
- Importance Ranking
- Confidence Ranking

---

## Version History

Memories never overwrite previous versions.

```
Version 1

↓

Version 2

↓

Version 3
```

History is immutable.

---

## Relationship Graph

Support for

- RELATED_TO
- BELONGS_TO
- DEPENDS_ON
- REFERENCES
- FOLLOW_UP
- CONTRADICTS
- SUPERSEDES
- PARENT_OF
- CHILD_OF

---

## Explainability

Every retrieval explains

- why it was retrieved
- ranking
- importance
- confidence
- relationship path

---

## Model Agnostic

Compatible with

- OpenAI
- Anthropic
- Google
- Ollama
- Llama
- Qwen
- DeepSeek

or any future LLM.

---

# High-Level Architecture

```
AI Agent

↓

REST API / MCP

↓

Memory Kernel

↓

Core Services

├── Memory Engine
├── Retrieval Engine
├── Graph Engine
├── Version Engine
├── Permission Engine
└── Importance Engine

↓

Storage Layer

├── PostgreSQL / SQLite
├── Neo4j
└── Qdrant
```

---

# Tech Stack

### Backend

- Python
- FastAPI

### Metadata Storage

- SQLite
- PostgreSQL

### Graph Database

- Neo4j

### Vector Database

- Qdrant

### Dashboard

- React
- TypeScript

### Containerization

- Docker

### Protocols

- REST API
- MCP (Model Context Protocol)

---

# Repository Structure

```
MemOS/

├── docs/
│   ├── PRD.md
│   ├── SRS.md
│   ├── MemoryTheory.md
│   ├── SystemArchitecture.md
│   ├── Database.md
│   ├── Algorithms.md
│   ├── API.md
│   ├── MCP.md
│   ├── Dashboard.md
│   ├── Security.md
│   ├── Benchmarks.md
│   ├── Roadmap.md
│   └── Research.md
│
├── backend/
│
├── dashboard/
│
├── sdk/
│
├── tests/
│
└── README.md
```

---

# Documentation

The project is documented from first principles.

| Document | Description |
|----------|-------------|
| PRD | Product vision and goals |
| SRS | Functional and non-functional requirements |
| MemoryTheory | Formal theory of AI memory |
| SystemArchitecture | System-level architecture |
| Database | Database and storage design |
| Algorithms | Retrieval and scoring algorithms |
| API | REST API specification |
| MCP | Model Context Protocol integration |
| Dashboard | Dashboard design |
| Security | Security architecture |
| Benchmarks | Performance evaluation |
| Roadmap | Product evolution |
| Research | Novel contributions and future work |

---

# Current Status

## Phase

**Documentation & Architecture**

Completed

- ✅ PRD
- ✅ SRS
- ✅ Memory Theory
- ✅ System Architecture
- ✅ Database Design
- ✅ API Specification
- ✅ MCP Specification
- ✅ Security Specification
- ✅ Benchmark Specification
- ✅ Roadmap

In Progress

- ⏳ Algorithms
- ⏳ Dashboard
- ⏳ Research
- ⏳ Backend Development
- ⏳ Memory Kernel

Upcoming

- ✅ REST API
- ✅ MCP Server
- ⏳ Dashboard
- ⏳ Testing
- ⏳ Docker Deployment

---

# Version Roadmap

## Version 1

- Deterministic Memory OS
- Hybrid Retrieval
- Memory Objects
- REST API
- MCP Server

---

## Version 2

- Reflection Engine
- Memory Decay
- Consolidation
- Plugin System

---

## Version 3

- Distributed Memory
- Multi-Agent Support
- Cloud Deployment

---

## Version 4

- Self-Evolving Memory
- Knowledge Abstraction
- Adaptive Retrieval

---

# Research Goals

MemOS explores several open research problems including

- AI Memory Operating Systems
- Hybrid Graph + Vector Retrieval
- Memory Importance Algorithms
- Memory Evolution
- Explainable Memory Retrieval
- Persistent AI Memory
- Multi-Agent Memory Systems

---

# Why MemOS?

Every AI application today reinvents memory.

MemOS aims to provide one reusable, standardized memory layer for all AI systems.

Instead of building memory again and again,

developers can simply connect to MemOS.

---

# Contributing

Contributions are welcome.

Areas of interest include

- Memory Algorithms
- Retrieval Systems
- Graph Databases
- AI Infrastructure
- Distributed Systems
- Backend Engineering
- Dashboard Development
- Documentation

---

# Future

The long-term vision is for MemOS to become the standard memory infrastructure for AI systems, similar to how operating systems became the standard abstraction for hardware and relational databases became the standard abstraction for structured data.

---

# License

MIT License

---

# Author

**Manthan S. Gadiya**

Bachelor of Technology (Artificial Intelligence & Data Science)

Research Interests

- AI Systems
- Explainable AI
- AI Infrastructure
- Memory Architectures
- Multi-Agent Systems
- Distributed Systems

---

> **"Reasoning makes AI intelligent. Memory makes AI persistent."**