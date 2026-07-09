"""Run all Neo4j-dependent smoke tests in order.

Usage (once Docker Desktop is running and Neo4j container is up):

  docker run -d --name neo4j-dev -p 7687:7687 -e NEO4J_AUTH=neo4j/neo4j neo4j:5
  # wait ~15s for startup
  python tests/run_smoke.py

Environment variables (defaults shown):
  NEO4J_URI      bolt://localhost:7687
  NEO4J_USER     neo4j
  NEO4J_PASSWORD neo4j
  LLM_MOCK       true
"""
import asyncio
import importlib
import subprocess
import sys
import socket
import time


def _wait_for_neo4j(host="localhost", port=7687, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                print(f"  Neo4j:{port} ready")
                return True
        except OSError:
            time.sleep(2)
    return False


def _run(script: str) -> bool:
    print(f"\n{'='*60}")
    print(f"  Running {script}")
    print('='*60)
    result = subprocess.run([sys.executable, script], capture_output=False)
    return result.returncode == 0


if __name__ == "__main__":
    import os
    os.environ.setdefault("LLM_MOCK", "true")
    os.environ.setdefault("LOCAL_DEV", "true")
    os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
    os.environ.setdefault("NEO4J_USER", "neo4j")
    os.environ.setdefault("NEO4J_PASSWORD", "neo4j")

    print("Waiting for Neo4j on bolt://localhost:7687 ...")
    if not _wait_for_neo4j():
        print("ERROR: Neo4j not reachable. Start it first:")
        print("  docker run -d --name neo4j-dev -p 7687:7687 -e NEO4J_AUTH=neo4j/neo4j neo4j:5")
        sys.exit(1)

    scripts = [
        "tests/smoke_neo4j.py",
        "tests/smoke_profile_graph.py",
        "tests/smoke_tailor_graph.py",
    ]

    results = {}
    for s in scripts:
        results[s] = _run(s)

    print(f"\n{'='*60}")
    print("SMOKE TEST RESULTS:")
    all_ok = True
    for s, ok in results.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {s}")
        if not ok:
            all_ok = False

    sys.exit(0 if all_ok else 1)
