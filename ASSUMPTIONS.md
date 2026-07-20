# FactoryOS Assumptions

1. **Authentication & Sessions**: A real multi-tenant agency tool would require secure OAuth, JWTs, and isolated organizations. For this prototype, a simple cookie-based session with a dummy user table and role switcher handles authentication as requested.
2. **Database Choice**: SQLite (via SQLAlchemy) is used for frictionless demo execution. JSON columns are used for complex payloads (structured brief, structured proposal) to avoid over-normalizing data for a prototype.
3. **LLM Parsing & Fallbacks**: Generating structured JSON natively from an LLM can occasionally fail or return wrapped markdown. The agent code includes a robust regex/string stripping fallback to remove ````json` wrappers and will automatically retry once on Pydantic validation failure.
4. **Agent Concurrency**: The agent runs synchronously on upload. In a real-world scenario, this would likely be offloaded to a message queue (Celery/RabbitMQ) with websockets pushing progress to the UI. For the pitch, synchronous execution provides immediate gratification.
5. **UI Framework**: React with Vite and Tailwind provides the most modern, editorial aesthetic while remaining extremely lean (no heavy UI frameworks).
6. **Activity Log**: Event history is maintained centrally in `agent_events`. It does not show the LLM's internal token deliberation step-by-step; rather, it uses a generated "reasoning summary" to keep the UI clean for Account Managers.
