# PokerHelper v2

九人桌德州扑克的本地识别、行动记录与范围分析工具。使用 Python、OpenCV 和 PyQt5。

A local observation, action-history and range-analysis tool for nine-player Texas Hold'em, built with Python, OpenCV and PyQt5.

**策略为启发式范围模型，并非 GTO 求解器。 / This is a heuristic range model, not a GTO solver.**

## 中文说明

### 功能

- 分别识别手牌、公共牌、玩家下注与底池，连续确认后再用于分析。
- 使用整数分记账；缺少小数点时暂停识别，不猜金额。
- 跟踪已观察到的下注变化，校验底池、下注和剩余筹码的一致性。
- 随可确认的行动更新对手组合权重，最多计算八名对手；平局按人数分池。
- 展示底池赔率、逐人有效筹码与 SPR、条件跟注 EV，以及完整记录条件下的主池/边池分析。
- 提示同花、公共牌配对后的葫芦/四条风险、顺子组合示例和下一张成牌张数。
- 支持坐标编辑、本地诊断和 JSON 牌局回放。

### 隐私与模板

**本仓库不上传截图、从截图裁出的识别模板、玩家名称图片、日志或诊断结果。** 相关目录和所有图片扩展名已加入 `.gitignore`。示例牌局是人工构造的数据，不包含玩家账号。

识别模板需在自己的电脑本地准备，放入以下目录；不要将模板或个人截图提交到仓库：

```text
templates/
  hero/        # 2–9, T, J, Q, K, A 与 s, h, d, c 的 PNG 模板
  board/       # 公共牌点数与花色 PNG 模板
  bets_digits/ # 玩家下注/亮色余额：0–9 和 dot.png
  digits/      # 中央底池：0–9 和 dot.png
  dim_digits/  # 暗色余额：0–9 和 dot.png
  dealer.png   # 可选：庄位按钮；缺少时可手动指定庄位
```

`T.png` 代表 10，`s/h/d/c` 分别代表黑桃、红桃、方块、梅花。坐标保存在 `table_coords.json`，需按自己的桌面重新校准。模板缺失时，不能完成屏幕识别，但仍可运行不依赖图像的测试与 JSON 回放。

### 安装与运行

建议使用 Windows 和 Python 3.11 或更高版本；原项目在 Windows / Python 3.14 上验证。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main_hud.py
```

准备好本地模板后，确认参考分辨率、偏移、自己座位、大盲、庄位、抽水和各座位状态，点击“应用设置”。必须明确中央底池是否已包含当轮下注，避免重复计数。程序不会把筹码亮暗当作弃牌证据；每手需核对在局内、已弃牌、全下和空座。

```powershell
python -m unittest discover -s tests -v
python -m poker_helper.replay examples/hand_replay.json replay_result.json
python -m PyInstaller --noconfirm PokerHelperV2.spec
```

打包需要本地模板。输出为 `dist/PokerHelperV2/PokerHelperV2.exe`。私有图像和模板缺失时，相应视觉测试会明确跳过，其他测试仍会执行。原始本地完整数据集验证了 31 项测试；不代表所有桌面或平台都能准确识别。

### 限制

范围根据默认先验和已观察动作估计，不能确定对手底牌。多人同时改变下注时，不猜行动先后；没有金额变化时，不猜过牌。历史不完整时，范围与边池资格可能无法可靠还原，程序会显示提示或暂停建议。

跟注 EV 是假设后续不再加注的条件基准，未求解未来下注树，也未计算加注收益。模拟区间只描述抽样误差，不包含范围模型误差。人工开池表没有 GTO 求解来源；特殊抽水、保险、前注和比赛 ICM 没有建模。

## English documentation

### Features

- Separate recognition for hole cards, community cards, player wagers and the pot, with repeated-frame confirmation.
- Integer-cent accounting; uncertain or missing decimal points are rejected rather than guessed.
- An observed action ledger with pot, wager and remaining-stack consistency checks.
- Action-conditioned heuristic ranges for up to eight opponents, with correct split-pot shares.
- Pot odds, per-opponent effective stacks and SPR, conditional call EV, and layered pot analysis when the contribution history is complete.
- Flush, paired-board/full-house/quads and straight warnings, plus next-card improvement counts.
- Coordinate editing, local diagnostics and JSON hand replay.

### Privacy and local assets

**Screenshots, cropped recognition templates, player-name images, logs and diagnostics are excluded from this repository.** Image extensions and private asset directories are ignored. The example hand is synthetic and contains no player accounts.

Prepare your own local PNG templates using the directory layout above. `T.png` means ten; `s/h/d/c` mean spades, hearts, diamonds and clubs. Wager and pot groups contain `0.png` through `9.png` and `dot.png`. The dealer marker is optional because its seat can be selected manually. Calibrate `table_coords.json` for your own desktop. Do not commit private assets.

### Setup

Windows and Python 3.11+ are recommended. The original local project was validated on Windows with Python 3.14. Create a virtual environment, install `requirements.txt`, then run `main_hud.py` using the commands above.

After supplying local templates, confirm the reference resolution, offsets, hero seat, blinds, dealer, rake and seat statuses. Explicitly select whether the central pot already includes current wagers. Seat status requires confirmation; text brightness is not treated as proof that a player folded.

Run tests with `python -m unittest discover -s tests -v`. Replay the synthetic hand with `python -m poker_helper.replay examples/hand_replay.json replay_result.json`. Build the Windows application with `python -m PyInstaller --noconfirm PokerHelperV2.spec` after adding local assets. Output: `dist/PokerHelperV2/PokerHelperV2.exe`.

Tests requiring private images or templates are explicitly skipped when those files are absent. The original complete local dataset passed 31 tests; this does not establish accuracy across all desktops or poker clients.

### Limitations

Ranges are heuristic estimates based on priors and observed actions, not knowledge of an opponent's hidden cards. Simultaneous wager changes are marked as unordered; missing wager changes are not interpreted as checks. An incomplete ledger can prevent reliable side-pot eligibility calculations.

Call EV assumes no further raises and does not solve future betting or raise EV. Simulation intervals cover sampling error only, not range-model uncertainty. Opening charts are manually specified and are not solver-derived. Platform-specific rake, insurance, antes and tournament ICM are not modeled.

## Source layout / 代码结构

| Path | Purpose / 用途 |
| --- | --- |
| `poker_helper/vision.py` | Local recognition / 本地识别 |
| `poker_helper/state.py` | Confirmation and action ledger / 确认与行动记账 |
| `poker_helper/ranges.py` | Heuristic ranges and simulation / 范围与模拟 |
| `poker_helper/analysis.py` | Conditional analysis / 条件决策分析 |
| `poker_helper/ui.py` | Desktop UI / 桌面界面 |
| `engine.py` | Legacy evaluator used as a test oracle / 测试对照用旧牌型评估器 |
| `examples/hand_replay.json` | Synthetic replay / 人工构造的回放示例 |

No license has been selected for this repository. / 本仓库尚未指定开源许可证。
