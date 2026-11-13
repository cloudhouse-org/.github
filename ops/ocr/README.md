# CloudHouse 组织级 OpenCodeReview

组织仓库里的轻量触发工作流调用本仓库的可复用工作流；审查任务只调度到组织 runner group `cloudhouse-review`，由 `dyw-003-review` 执行。触发事件为 PR `opened`、`synchronize`、`reopened`，也可用 `workflow_dispatch` 指定一个开放 PR。

## 成员资格与信任边界

- 只接受目标仓库属于 `cloudhouse-org`、仍开放且基础分支属于该仓库的 PR。
- 审查前从 GitHub PR API 读取实时 `author_association`，仅放行 `MEMBER` 和 `OWNER`。发布每条意见前再次读取 PR 状态、head SHA、目标仓库和成员关系；PR 关闭、更新或作者失去成员资格时丢弃结果。
- 支持组织成员从 fork 提交的 PR。其他仓库的外部成员身份或协作者关系不会放行。
- 审查工作树检出目标仓库的可信 base SHA，只抓取 PR Git 对象用于 diff；不 checkout、不执行、不加载 PR 分支中的规则或脚本。
- `cloudhouse-review` runner group 必须限制为本可复用 workflow 的完整路径和固定 SHA。不要把标签当作权限边界，也不要将此 runner 加入 CI 或 production runner group。
- 检查是建议性的，不自动批准或请求变更；不要将 OCR 状态设为合并必需检查。

## 配置与本机凭据

仅在 `cloudhouse-org` 的**未归档私有仓库**安装调用 workflow。可复用 workflow 会再次检查仓库为私有、PR 仍开放、base 属于当前仓库，并且 PR 作者的 `author_association` 为 `MEMBER` 或 `OWNER`；公共仓库不会进入审查任务。`cloudhouse-review` runner group 禁止公共仓库，并只允许调用固定 SHA 的本可复用 workflow。

每个私有仓库单独配置以下 Actions variables（变量不是凭据）：

| 名称 | 要求 |
| --- | --- |
| `OCR_REVIEW_ENABLED` | 严格设为 `true` 才启用 |
| `OCR_LLM_MODEL` | 模型标识 |
| `OCR_USE_ANTHROPIC` | `true` 或 `false` |

API 地址固定为 `https://coding.dashscope.aliyuncs.com/v1`，不读取仓库可修改的 URL 变量，避免把 dyw-003 本机 token 转发到其他地址。每个私有仓库只需配置模型标识和协议变量。GitHub Actions secret 不用于这条链路。模型 token 只保存在 dyw-003 的 `/etc/cloudhouse-review/ocr-token`，所有者为 `root:cloudhouse-review`、权限为 `0640`；父目录为 `root:cloudhouse-review`、权限为 `0750`。只有专用 `cloudhouse-review` runner 账户所属组可以读取。审查步骤仅在运行时读取，并将 token 限定在该步骤的进程环境中，不写入 workflow 输出或 GitHub 日志。

在 dyw-003 上以 root 交互运行 `ops/ocr/setup-runner-token.sh`，在隐藏提示中输入专用模型 token。脚本不会回显或覆盖已有 token 文件。不要把 token 写进命令参数、仓库、Issue、PR 或聊天；轮换时按运维流程先移除旧文件再重新安装。若本机凭据文件或权限不符合要求，审查任务会失败关闭。

无需 `OCR_ORG_MEMBERSHIP_TOKEN`：成员资格以 GitHub 返回的 PR `author_association` 判断，并在发布时复核。

## 仓库规则与审查成本

若目标仓库可信 base 分支有普通文件 `ops/ocr/rules.json` 或 `ops/ocr/background.md`，审查使用这些文件；否则回退到本仓库内的通用规则。规则只从 base SHA 读取，PR 分支不能覆盖。

OpenCodeReview Linux x64 二进制固定为 v1.12.11，并按 SHA-256 校验。每次最多 500,000 tokens、2 路并发、单次分析 10 分钟、job 45 分钟、模型请求超时 120 秒。模型服务商会收到审查所需的 PR diff 和可信背景；必须确保该数据处理符合组织的代码与隐私策略，并在服务商侧设置账户限额。

不为公共仓库开启 `cloudhouse-review` runner group。即使当前 workflow 不执行 PR 代码，公共仓库和外部贡献场景也不属于此本机凭据审查的信任范围。
