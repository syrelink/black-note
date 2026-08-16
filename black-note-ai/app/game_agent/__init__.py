"""GameRover Agent 包的公共入口。

这是一个带上下文预算控制的单 Agent 游戏信息 Harness。外部模块只需要从
这里导入构建函数，不必依赖 graph.py 的内部实现。
"""

from app.game_agent.graph import GameAgentHarness, build_game_assistant

# 明确包对外承诺的 API，避免内部辅助类被误当成公共接口使用。
__all__ = ["GameAgentHarness", "build_game_assistant"]
