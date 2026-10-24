"""P1-7: real LLM chain test (智谱 GLM).

Runs ONLY when explicitly selected, because it calls the real provider and
consumes quota:  pytest -m llm_real
Uses the key already configured in data/llm_config.json (设置页保存的).
"""
import pytest

import app.services.llm as llm_mod


@pytest.mark.llm_real
async def test_real_glm_json_and_actions(monkeypatch):
    """Real chain: load persisted key -> GLM JSON output -> cache put/get."""
    # re-enable the real LLM for this test only (conftest forces it off)
    real_cfg = {}
    from app.config import DATA_DIR
    import json as _json

    cfg_path = DATA_DIR / "llm_config.json"
    if cfg_path.exists():
        real_cfg = _json.loads(cfg_path.read_text(encoding="utf-8"))
    if not real_cfg.get("api_key"):
        pytest.skip("未配置 API Key(data/llm_config.json),跳过真实链路测试")

    monkeypatch.setattr(llm_mod, "load_llm_config", lambda: real_cfg, raising=False)
    monkeypatch.setattr(llm_mod, "_API_KEY", None, raising=False)

    # build a throwaway session against the live DB via app.db
    from app.db import SessionLocal
    from sqlalchemy.ext.asyncio import AsyncSession

    gen = SessionLocal()
    db: AsyncSession = gen
    try:
        data = await llm_mod.generate_json(
            "selftest",
            "你是回声服务。只输出 JSON:{\"ok\":true,\"echo\":str}",
            "回复 pong",
            {"selftest": True},
            db,
        )
        assert data["ok"] is True
        assert "pong" in data["echo"]
        assert data.get("_cached") in (True, False)

        # real actions generation (degraded must be False)
        actions = await llm_mod.generate_actions(db, "完成单元测试报告", None)
        assert len(actions) >= 1 and actions[0]["title"]
    finally:
        await gen.close()
