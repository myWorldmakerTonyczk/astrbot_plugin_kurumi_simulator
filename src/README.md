# 源码结构

- `core/`：虚拟账本、统一交易执行入口、账户提醒
- `market_data/`：行情适配、行情设置、接口配置加载、历史 K 线与参考汇率
- `users/`：虚拟用户、随机 ID、会话身份与实例选择
- `agent/`：定时静默调用 LLM、交易上下文与决策工具
- `tools/`：面向聊天 LLM 的工具，每个工具一个文件，`registry.py` 统一注册
- `integration/`：AstrBot 生命周期、后台任务与 View API

插件发现入口仍为根目录 `main.py`；接口默认地址与名称为根目录 `config/market.json`。
行情和身份层可以使用账本；聊天工具与定时智能体统一调用 `core/trading.py`，避免绕过交易校验。

- `diary/`：每日经验日记、已授权聊天归档、日期边界、持久队列与只读检索
