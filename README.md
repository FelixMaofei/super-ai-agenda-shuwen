# Super AI Lab 会单 · 舒文版

2026-09-14 从伙伴的 `mingyuan-toastmasters-agenda-final.zip` 独立复制，现已通过第246期真实试用。原版会单 Skill 保留不动。来源校验信息见 `provenance.json`。

保留三项方法：AI 画主题、程序排准确文字；右侧与底部像素保持一致；正文保持字号，长内容换行并增加高度。

这次接入原 V4.2 时间计算结果，消除对伙伴个人字体路径的依赖，支持半分钟与无备稿输入，并补齐打包文件。使用说明见 [SKILL.md](SKILL.md)。

2026-09-23 的模板更新现已纳入：使用 2600×3719 最终底图，标题按语义分行并支持关键词强调，按期数输出会单与主图。标题字体由本机提供，获取与许可说明见 [FONT-LICENSE.md](FONT-LICENSE.md)。

在头马项目的新对话中可说：

> 用舒文版，为 Super AI Lab 做下一期会单。下面是本期接龙……

第246期最终采用图已获 Felix 认可。参考图和可复用规则见 `references/approved-style.md`。程序测试图和历史样例不作为下一期事实；本期最终采用原图保持不变。

维护检查：

```bash
python3 -m unittest discover -s tests -p 'test_shuwen.py'
python3 scripts/package_local.py --output-dir /tmp/shuwen-package-check
```

仓库与打包文件含模板中的俱乐部资料和二维码，当前按私有仓库管理。Python 需要 Pillow 与中文字体；可通过命令参数指定字体。

## GitHub 仓库

独立仓库：<https://github.com/FelixMaofei/super-ai-agenda-shuwen>（私有）。

拥有仓库访问权限后，可克隆到本机 Skill 目录：

```bash
git clone https://github.com/FelixMaofei/super-ai-agenda-shuwen.git ~/.agents/skills/super-ai-agenda-shuwen
```

仓库保留运行程序、必要模板素材、已认可版式参考和当前9项验证用例。临时渲染结果、旧V009探索稿和历史测试留在本地，不随仓库上传。源码中保留舒文伙伴包的来源信息，本仓库独立维护，不替换原通用会单仓库。
