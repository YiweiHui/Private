# 宏观指标信号看板

这是一个配置驱动的宏观防御信号看板。当前版本已经完成：

- 指标配置表维护；
- 本地历史数据读取；
- 防御信号计算；
- 一级维度加权得分；
- “一级维度 → 二级指标”的分级展示；
- 指标历史趋势图；
- Streamlit 网页部署所需文件。

> 当前示例数据仅用于验证看板逻辑和网页部署，不应直接用于投研判断。

## 1. 目录结构

```text
macro_signal_dashboard/
├─ app.py                              # Streamlit 看板入口
├─ requirements.txt                    # Streamlit Cloud / 本地运行依赖
├─ DEPLOYMENT.md                       # GitHub + Streamlit Cloud 部署说明
├─ run_demo.py                         # 命令行计算与导出示例
├─ .gitignore                          # 避免误传缓存、输出和真实敏感数据
├─ .streamlit/
│  ├─ config.toml                      # 页面主题配置
│  └─ secrets.example.toml             # Secrets 示例，不含真实密钥
├─ data/
│  ├─ indicator_config.xlsx            # 指标规则配置表，可直接编辑
│  ├─ indicator_config.csv             # 同内容 CSV 版本
│  ├─ macro_series_template.csv        # 演示历史数据
│  ├─ macro_series_blank_template.csv  # 空白数据模板
│  └─ README_DATA.md                   # 数据格式说明
├─ src/
│  ├─ data_loader.py                   # 本地文件读取，不含取数接口
│  ├─ signal_engine.py                 # 信号计算核心
│  ├─ scoring.py                       # 总分解释
│  └─ ui_components.py                 # 前端组件
└─ tests/
   └─ test_signal_engine.py            # 核心逻辑测试
```

## 2. 本地运行

Windows 推荐使用：

```cmd
cd /d "%USERPROFILE%\Desktop\macro_signal_dashboard"
py -m pip install -r requirements.txt
py -m streamlit run app.py
```

macOS / Linux：

```bash
cd macro_signal_dashboard
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

如果只想验证计算逻辑，不打开网页：

```bash
python run_demo.py
```

## 3. 部署为网页

本项目不能直接用 GitHub Pages 部署，因为它是 Streamlit / Python 应用，不是纯静态网页。

推荐路径：

```text
GitHub 仓库存代码 → Streamlit Community Cloud 部署 → 团队成员浏览器访问
```

详细步骤见：

```text
DEPLOYMENT.md
```

## 4. 历史数据格式

数据获取模块还没接入时，只要把 Wind / Excel / 手工数据整理成下面三列即可：

| date | indicator_id | value |
|---|---|---:|
| 2026-06-30 | PMI_MFG | 50.30 |
| 2026-06-30 | CPI_YOY | 1.20 |

注意：

- `date`：指标日期；
- `indicator_id`：必须与 `indicator_config.xlsx` 中的 `indicator_id` 完全一致；
- `value`：数值本身。百分比类指标请直接填“百分点数”，例如 1.20% 填 `1.20`，不要填 `0.012`。

## 5. 配置表字段说明

| 字段 | 含义 |
|---|---|
| display_order | 展示顺序 |
| dimension | 一级维度，例如经济景气、通胀水平 |
| dimension_weight | 一级维度权重，可填 0.25 或 25 |
| indicator_id | 指标唯一 ID，必须与历史数据一致 |
| indicator_name | 前端展示名称 |
| unit | 展示单位，例如 `%`、`pp` |
| rule_type | `moving_avg`、`mom`、`fixed` |
| direction | `below`、`above`、`down`、`up` |
| ma_window | 移动平均窗口，适用于 `moving_avg` |
| threshold | 固定阈值，适用于 `fixed` |
| ma_include_latest | 移动平均是否包含最新一期，默认 FALSE |
| signal_text | 前端展示的规则文字 |
| digits | 小数位数 |
| enabled | 是否启用该指标 |
| remark | 备注 |

## 6. 正式接入数据源时怎么改

保留 `signal_engine.py`、`scoring.py` 和 `ui_components.py` 不动。

只需要让真实取数模块最终输出：

```text
date, indicator_id, value
```

然后替换：

```text
data/macro_series_template.csv
```

或在 `src/data_loader.py` 前面新增 Wind / Excel / 数据库取数函数。

## 7. 合规提醒

演示版可以放 GitHub 和 Streamlit Cloud。正式版如果涉及真实 Wind 数据、客户信息、信托产品持仓、赎回测算、内部月报等内容，建议部署在公司内网服务器，不建议放公网。
