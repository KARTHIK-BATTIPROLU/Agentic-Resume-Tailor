"""Test configuration — enable mock LLM and in-memory Neo4j bypass."""
import os

# Enable mock LLM so tests never hit the Groq API.
os.environ.setdefault("LLM_MOCK", "true")
os.environ.setdefault("LOCAL_DEV", "true")
# Prevent pydantic-settings from trying to read .env during tests.
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "neo4j")
