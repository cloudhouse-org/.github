# CloudHouse 组织级 OpenCodeReview

组织仓库里的轻量触发工作流调用本仓库的可复用工作流；审查任务只调度到组织 runner group `cloudhouse-review`，由 `dyw-003-review` 执行。触发事件为 PR `opened`、`synchronize`、`reopened`，也可用 `workflow_dispatch` 指定一个开放 PR。

## 成员资格与信任边界

- 只接受目标仓库属于 `cloudhouse-org`、仍开放且基础分支属于该仓库的 PR。
- 审查前从 GitHub PR API 读取实时 `author_association`，仅放行 `MEMBER` 和 `OWNER`。发布每条意见前再次读取 PR 状态、head SHA、目标仓库和成员关系；PR 关闭、更新或作者失去成员资格时丢弃结果。
- 支持组织成员从 fork 提交的 PR。其他仓库的外部成员身份或协作者关系不会放行。
- 审查工作树检出目标仓库的可信 base SHA，只抓取 PR Git 对象用于 diff；不 checkout、不执行、不加载 PR 分支中的规则或脚本。
- `cloudhouse-review` runner group 必须限制为本可复用 workflow 的完整路径和固定 SHA。不要把标签当作权限边界，也不要将此 runner 加入 CI 或 production runner group。
- 检查是建议性的，不自动批准或请求变更；不要将 OCR 状态设为合并必需检查。

## Actions 配置

组织级变量：

| 名称 | 示例/要求 |
| --- | --- |
| `OCR_REVIEW_ENABLED` | 严格设为 `true` 才启用 |
| `OCR_LLM_URL` | 使用 HTTPS 的兼容 API 地址 |
| `OCR_LLM_MODEL` | 模型标识 |
| `OCR_USE_ANTHROPIC` | `true` 或 `false` |

组织级 Actions secret：`OCR_LLM_TOKEN`。只向安装了组织触发 workflow 的仓库开放。若变量、token 或模型配置不完整，授权 job 会说明跳过原因，不会把 job 派给自托管 runner。

无需 `OCR_ORG_MEMBERSHIP_TOKEN`：成员资格以 GitHub 返回的 PR `author_association` 判断，并在发布时复核。

## 仓库规则与审查成本

若目标仓库可信 base 分支有普通文件 `ops/ocr/rules.json` 或 `ops/ocr/background.md`，审查使用这些文件；否则回退到本仓库内的通用规则。规则只从 base SHA 读取，PR 分支不能覆盖。

OpenCodeReview Linux x64 二进制固定为 v1.12.11，并按 SHA-256 校验。每次最多 500,000 tokens、2 路并发、单次分析 10 分钟、job 45 分钟、模型请求超时 120 秒。模型服务商会收到审查所需的 PR diff 和可信背景；必须确保该数据处理符合组织的代码与隐私策略，并在服务商侧设置账户限额。

GitHub 对公共仓库自托管 runner 有额外风险提示。为覆盖组织公共仓库，runner group 可启用 public repository access，但必须继续限制为固定 SHA 的本可复用 workflow；该 workflow 不执行 PR 代码。若修改访问限制，重新核对所有允许的 workflow 路径。
