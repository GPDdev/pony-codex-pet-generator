# Pony Codex Pet Generator

<div align="center"><img alt="Tests" src="https://github.com/GPDdev/pony-codex-pet-generator/actions/workflows/test.yml/badge.svg"><img alt="Version" src="https://img.shields.io/badge/version-0.1.0-blue"><img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-blue"><img alt="License" src="https://img.shields.io/badge/license-MIT-green"></div>

把 Pony Town 导出的透明 GIF 转成 Codex 原生桌宠：自动识别动作、统一像素缩放、生成左右朝向，并导出安装包和动画预览。完全本地处理，无需 AI API、账户或网络上传。

目录：[简介](#简介) · [安装](#安装) · [使用](#使用) · [动作映射](#动作映射) · [参数与接口](#参数与接口) · [限制](#限制) · [参与贡献](#参与贡献) · [许可](#许可)

## 简介

提供 Python 命令行和简单的图形界面，适合想把自己 Pony Town 角色带到桌面上的玩家。不是网页桌宠，也不会改写 Codex 客户端。

输出包括 `pet.json`、透明 `spritesheet.webp`、仅含安装文件的 ZIP、九种动作 GIF 预览、`preview.html`、`contact-sheet.png` 和不包含本机绝对路径的 `report.json`。

目标格式：v1，1536 × 1872 像素，8 列 × 9 行，每格 192 × 208 像素。填充 57 格，剩余 15 格透明。所有动作共享同一缩放比例，使用最近邻缩放保留像素边缘，不对小素材自动放大。

## 安装

需要 Python 3.10 或更新版本，以及 Pillow。图形界面还需要 tkinter；Windows/macOS 的官方 Python 安装通常包含它，Linux 可通过系统包安装（例如 `python3-tk`）。

```bash
git clone https://github.com/GPDdev/pony-codex-pet-generator.git
cd pony-codex-pet-generator
python -m pip install -r requirements.txt
```

## 使用

### 图形界面

```bash
python generate_pet.py --gui
```

选择一个角色的 GIF 文件夹，填写桌宠名称和 ID，再选择一个**尚不存在**的输出目录。点“自动匹配”，检查九个动作的 GIF，最后点“生成桌宠”。可以手动选择动作、设置镜像、指定从 0 开始的帧索引；留空则自动采样。

“素材朝向”指输入 GIF 的共同朝向，默认右。导出时生成相应的左右拖拽动作。生成后点“打开预览”查看结果。

### 命令行

```bash
python generate_pet.py ./my-gifs --output ./output/my-pony --name "My Pony" --id my-pony
```

原始 Pony Town 文件名无需改名，例如：

```text
my-gifs/
  pony-town-My Pony-stand-blinking-padded-4x.gif
  pony-town-My Pony-fly-blinking-padded-4x.gif
  pony-town-My Pony-applause-blinking-padded-4x.gif
  pony-town-My Pony-dance move 1-blinking-padded-4x.gif
  pony-town-My Pony-yawn-blinking-padded-4x.gif
  pony-town-My Pony-boop-blinking-padded-4x.gif
  pony-town-My Pony-dance-4-blinking-padded-4x.gif
  pony-town-My Pony-sit-blinking-padded-4x.gif
```

也支持简短名称，如 `stand.gif`、`fly.gif`。只搜索文件夹第一层；推荐一个文件夹只放一个角色、同一倍率、相同朝向的导出。同一动作有多份文件时不会随意选择，会提示使用手动映射。

### 安装生成的桌宠

解压输出 ZIP，把其中的 `<pet-id>` 文件夹放入 `~/.codex/pets/`。Windows 默认位置是 `%USERPROFILE%\.codex\pets\`。最终结构：

```text
~/.codex/pets/my-pony/
  pet.json
  spritesheet.webp
```

在 Settings → Pets 中点 Refresh，选择桌宠，再用 `/pet` 显示或隐藏。具体界面及可用性见 [OpenAI 官方 Pets 文档](https://learn.chatgpt.com/docs/pets)。本程序不会自动修改客户端、激活桌宠或覆盖已安装的文件。已有同 ID 桌宠时，请先备份，再手动替换。

## 动作映射

| Codex 状态 | 优先素材 | 缺失时回退 |
| --- | --- | --- |
| idle | stand | 无；需提供 stand 或明确映射 |
| running-right | fly | trot → stand |
| running-left | fly，镜像 | trot → stand |
| waving | applause | laugh → stand |
| jumping | dance move 1 | trot → stand |
| failed | yawn | lie → stand |
| waiting | boop | stand |
| running | dance-4 | trot → stand |
| review | sit | lie → stand |

同名状态文件（如 `waving.gif`）优先于上述动作匹配。自动采样按 GIF 时间轴选择帧；空闲状态以停留最长的画面为站立、短时的不同画面为眨眼候选，安排一次约 0.66 秒的候选帧和约 5.94 秒的站立。

> [!NOTE]
> 眨眼候选是时长启发式，不是眼睛识别。特殊素材可能选到非眨眼帧；请预览后手动指定帧。动作缺失会回退并记录警告，不会凭空绘制新动作。

### 自定义映射

```bash
python generate_pet.py ./my-gifs --output ./output/custom-pony --mapping example-mapping.json
```

`example-mapping.json` 假设输入文件已命名为 `stand.gif` 和 `fly.gif`，且 `stand.gif` 至少有三帧；使用原始长文件名时修改 `file`。配置可只覆盖部分状态：

```json
{
  "idle": {
    "file": "stand.gif",
    "frames": [0, 2, 0, 0, 0, 0],
    "mirror": false
  },
  "running-left": {
    "file": "fly.gif",
    "mirror": true
  }
}
```

`frames` 从 0 开始，必须与目标行的格数相同：idle 6；running-right/left 8；waving 4；jumping 5；failed 8；waiting/running/review 6。`mirror` 表示相对标准右向素材是否镜像，之后再结合全局 `--facing` 调整；通常只有 running-left 为 true。所有文件必须直接位于输入文件夹内。

## 参数与接口

```bash
python generate_pet.py --help
python generate_pet.py --version
```

| 参数 | 默认值 | 用途 |
| --- | --- | --- |
| source | 无 | 透明 GIF 文件夹；命令行转换必填 |
| --output | output/my-pony | 新输出目录；拒绝覆盖 |
| --name | My Pony | 显示名称，1–100 字符 |
| --id | my-pony | 小写字母、数字和单连字符，1–80 字符 |
| --description | Pony Town companion | 最多 1000 字符 |
| --mapping | 无 | JSON 状态映射覆盖 |
| --scale | 自动适配 | 全部动作的统一缩放；超出安全边界会报错 |
| --facing | right | 输入素材共同朝向：right / left |
| --gui | 关闭 | 打开图形界面 |

也可以从 Python 调用：

```python
from generate_pet import generate

report = generate("./my-gifs", "./output/my-pony", name="My Pony", pet_id="my-pony")
print(report["warnings"])
```

`generate(source, output, name="My Pony", pet_id="my-pony", description="Pony Town companion", mapping=None, scale=None, facing="right")` 返回转换报告。无效输入抛出 `ValueError`，文件错误可能抛出 `OSError`。转换失败会清理临时文件，不留下半成品输出目录。

## 限制

- 仅生成现有客户端使用的 v1 图集，不生成 v2 看向角度，也不提供自定义客户端行为脚本。
- 鼠标事件、动作触发、播放速度、循环次数、最终桌宠显示大小及朝向保持由客户端控制，不能只靠 `pet.json` 任意修改。
- 源 GIF 必须透明；不会自动抠背景。单文件上限 2048 像素边长、1000 帧、解码后 1 亿像素。
- 每行最多 8 帧，会压缩较长动画；输出预览使用 v1 的固定节奏，不保留原 GIF 的全部帧和原始速度。
- 各素材必须是同一角色、相同导出倍率和共同朝向，自动识别不会判断角色身份或补齐缺失动作。
- 图形界面和命令行需要 Python；此仓库暂不提供独立 EXE。不会发送 GIF 到任何服务器。

## 参与贡献

欢迎提交带有可复现步骤的 Issue 或 PR。请只使用自己有权使用、发布的角色素材。

```bash
python -m unittest -v
```

测试使用合成透明 GIF，不捆绑玩家素材；覆盖图集结构、左右镜像、固定预览时长、ZIP 内容、统一缩放、参数检查、拒绝覆盖及失败清理。GitHub Actions 在 Windows 和 Linux 上运行同一测试。

## 许可

生成器代码采用 [MIT 许可证](LICENSE)。输入角色、Pony Town 美术和第三方素材的权利归各自权利人；生成器不授予发布或再分发这些素材的权利。本项目不是 Pony Town 或 OpenAI 官方项目。
