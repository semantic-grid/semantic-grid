# Architecture Documentation

Technical architecture documentation for Semantic Grid.

## Structure

### `v1/`
Current production architecture (legacy):
- `web-app-structure.md` - Frontend architecture (routes, contexts, components)

### `v2/`
V2 architecture (message-based, notebook-style):
- `api-v2-implementation.md` - Backend API v2 design
- `flexible-chat-v2.md` - V2 chat architecture (comprehensive)
- `v2-agentic-framework.md` - Agentic workflow system
- `v2-frontend-architecture.md` - Frontend v2 technical reference
- `v2-migration-strategy.md` - How to migrate v1 → v2
- `v2-prompt-pack-structure.md` - Prompt pack system
- `v2-worker-flows.md` - Worker architecture and flows

## Quick Reference

**Understanding current system**: Start with `v1/web-app-structure.md`

**Building v2 frontend**: Read in order:
1. `v2/v2-frontend-architecture.md` - Technical architecture
2. `v2/v2-migration-strategy.md` - Implementation approach
3. `v2/flexible-chat-v2.md` - Comprehensive design (optional deep dive)

**Backend v2**: Already implemented and deployed
- `v2/api-v2-implementation.md` - API endpoints
- `v2/v2-worker-flows.md` - How workers process messages
- `v2/v2-agentic-framework.md` - Agentic system design
