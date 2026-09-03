import asyncio
import tempfile
from pathlib import Path

import httpx


async def run_live_smoke_test() -> None:
    base_url = "http://localhost:8000"
    print(f"=== Day 1 Live Integration Smoke Test ({base_url}) ===")

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        # 1. Test GET /health
        print("[1/6] Checking GET /health ...")
        resp = await client.get("/health")
        assert resp.status_code == 200, f"Health check failed: {resp.text}"
        data = resp.json()
        print(f"      PASS: {data}")

        # 2. Test CORS Headers
        print("[2/6] Checking CORS headers for http://localhost:5173 ...")
        resp = await client.options(
            "/api/v1/workspaces",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code == 200
        origin = resp.headers.get("access-control-allow-origin")
        assert origin == "http://localhost:5173", f"CORS origin mismatch: {origin}"
        print(f"      PASS: Access-Control-Allow-Origin = {origin}")

        # 3. Create a temporary folder on disk and register via POST /api/v1/workspaces
        print("[3/6] Testing POST /api/v1/workspaces and PostgreSQL persistence ...")
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_dir = Path(tmpdir).resolve()
            (sample_dir / "test_file.py").write_text(
                "print('smoke test')", encoding="utf-8"
            )

            create_resp = await client.post(
                "/api/v1/workspaces",
                json={"name": "live-smoke-workspace", "root_path": str(sample_dir)},
            )
            assert create_resp.status_code == 201, (
                f"Failed creating workspace: {create_resp.text}"
            )
            ws_id = create_resp.json()["id"]
            print(f"      PASS: Created workspace UUID = {ws_id}")

            # 4. Query workspace tree
            print(f"[4/6] Querying GET /api/v1/workspaces/{ws_id}/tree ...")
            tree_resp = await client.get(f"/api/v1/workspaces/{ws_id}/tree")
            assert tree_resp.status_code == 200, (
                f"Failed retrieving tree: {tree_resp.text}"
            )
            tree_data = tree_resp.json()
            assert any(node["name"] == "test_file.py" for node in tree_data["tree"])
            print(f"      PASS: Tree returned {tree_data['total_entries']} entries")

            # 5. Nonexistent path rejection
            print("[5/6] Verifying nonexistent paths are rejected ...")
            bad_resp = await client.post(
                "/api/v1/workspaces",
                json={"name": "bad", "root_path": "/invalid_path_dir_123"},
            )
            assert bad_resp.status_code == 400
            print(f"      PASS: Server returned HTTP {bad_resp.status_code}")

    # 6. Verify Frontend Dev Server
    print("[6/6] Checking Frontend server at http://localhost:5173 ...")
    async with httpx.AsyncClient(timeout=5.0) as client:
        fe_resp = await client.get("http://localhost:5173")
        assert fe_resp.status_code == 200, "Frontend server is not responding"
        assert (
            "IrtrixAI Coding Assistant" in fe_resp.text
            or '<div id="root">' in fe_resp.text
        )
        print("      PASS: Frontend serving React bundle at http://localhost:5173")

    print("\n=== ALL INTEGRATION VERIFICATION CHECKS PASSED ===")


if __name__ == "__main__":
    asyncio.run(run_live_smoke_test())
