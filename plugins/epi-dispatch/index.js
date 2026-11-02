import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const name = 'epi-dispatch'

const SKILL_CANDIDATES = [
  process.env.EPI_MODE_SKILL_DIR,
  path.join(os.homedir(), '.dsh', 'epi-mode', 'skills', 'epi-research-mode'),
  path.join(os.homedir(), '.agents', 'skills', 'epi-research-mode'),
].filter((value) => typeof value === 'string' && value.length > 0)

function skillDir() {
  for (const candidate of SKILL_CANDIDATES) {
    try {
      if (fs.existsSync(path.join(candidate, 'SKILL.md'))) return candidate
    } catch {}
  }
  return SKILL_CANDIDATES[1]
}

const ROLE_IDS = ['executor', 'plotter', 'reviewer']
const EFFORTS = new Set(['off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'])

const DEFAULTS = {
  executor: { label: '执行者', provider: 'deepseek-account', model: 'deepseek-flash', reasoningEffort: 'low' },
  plotter: { label: '画图者', provider: 'deepseek-account', model: 'deepseek-flash', reasoningEffort: 'low' },
  reviewer: { label: '审稿人', provider: 'deepseek-account', model: 'deepseek-flash', reasoningEffort: 'max' },
}

function readRoles() {
  const file = path.join(skillDir(), 'config', 'roles.json')
  let stored = {}
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (parsed && parsed.roles && typeof parsed.roles === 'object') stored = parsed.roles
  } catch {}
  const out = {}
  for (const id of ROLE_IDS) {
    const base = DEFAULTS[id]
    const row = stored[id] && typeof stored[id] === 'object' ? stored[id] : {}
    out[id] = {
      id,
      label: typeof row.label === 'string' && row.label ? row.label : base.label,
      provider: typeof row.provider === 'string' && row.provider ? row.provider : base.provider,
      model: typeof row.model === 'string' && row.model ? row.model : base.model,
      reasoningEffort: EFFORTS.has(row.reasoningEffort) ? row.reasoningEffort : base.reasoningEffort,
    }
  }
  return { file, roles: out }
}

const PARAMETERS = {
  type: 'object',
  properties: {
    role: {
      type: 'string',
      enum: ROLE_IDS,
      description: '要派给哪个角色。模型与推理强度取自技能目录 config/roles.json。',
    },
    prompt: {
      type: 'string',
      description: '完整、自包含的任务说明。子 agent 看不到本会话上下文。',
    },
    label: {
      type: 'string',
      description: '展示用短名，建议写成「角色·版本·子任务」。',
    },
    schema: {
      type: 'object',
      description: '可选的输出 JSON Schema（object 根）。给了就返回校验过的对象，否则返回文本。',
    },
    background: {
      type: 'boolean',
      description:
        'true = 立刻返回子代理 id 与后台状态，不阻塞本步，跑完结果作为通知投递回来；' +
        '默认 false = 等到跑完直接拿结果。要多路并发请在本条消息里多发几次调用，而不是靠 background。',
    },
  },
  required: ['role', 'prompt'],
}

const OUTPUT_SCHEMA = {
  type: 'object',
  properties: {
    role: { type: 'string' },
    stopReason: { type: 'string' },
    text: { type: 'string' },
    structured: { type: 'object' },
    diagnostic: { type: 'string' },
    route: { type: 'object' },
    subagentId: { type: 'string' },
    background: { type: 'boolean' },
  },
  required: ['role', 'stopReason', 'text'],
}

function textOf(output) {
  if (!Array.isArray(output)) return ''
  return output
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim()
}

export function apply(ctx) {
  const tools = ctx.get('tools')
  const subagents = ctx.get('subagents')
  if (!tools || !subagents) return

  ctx.effect(() =>
    tools.register({
      name: 'epi_dispatch',
      description:
        '按角色派发一个子 agent，并施加该角色配置的模型与推理强度。角色：executor（写码/跑数/出表）、plotter（作图）、reviewer（独立审稿）。' +
        '模型、推理强度、并发来自技能目录 config/roles.json（设置 → 科研模式 可改）。' +
        '需要在同一轮并行时，把多次 epi_dispatch 放进同一条消息一起调用。',
      parameters: PARAMETERS,
      output: {
        schema: OUTPUT_SCHEMA,
        render: (_args, value) => {
          const head = `[${value.role}] ${value.stopReason}` +
            (value.route ? ` · ${value.route.model}/${value.route.reasoningEffort ?? '默认'}` : '')
          const body = value.structured
            ? JSON.stringify(value.structured, null, 2)
            : value.text
          return [{ type: 'text', text: `${head}\n${body}` }]
        },
      },
      isConcurrencySafe: () => true,
      presentCall: (args) => ({
        card: 'generic',
        title: `epi_dispatch · ${args && args.role ? args.role : '?'}` +
          (args && args.background ? '（后台）' : ''),
        kind: 'execute',
      }),
      presentResult: (args, result) => {
        const value = result && result.value && typeof result.value === 'object' ? result.value : null
        if (!value) return undefined
        const route = value.route
          ? `${value.route.provider || '?'}/${value.route.model || '?'} @ ${value.route.reasoningEffort || '默认'}`
          : ''
        const head = value.background
          ? `${value.role} 已在后台启动 · ${route} · subagent ${value.subagentId || '?'}`
          : `${value.role} ${value.stopReason} · ${route}${value.subagentId ? ` · subagent ${value.subagentId}` : ''}`
        return {
          card: 'generic',
          title: head,
          content: [{ type: 'text', text: head }],
        }
      },
      async execute(args, exec) {
        const parent = exec.agent
        if (!parent) throw new Error('epi_dispatch 需要调用方 agent（exec.agent 为空）')
        const roleId = String(args && args.role || '')
        if (!ROLE_IDS.includes(roleId)) throw new Error(`未知角色：${roleId}`)
        const prompt = typeof args.prompt === 'string' ? args.prompt : ''
        if (!prompt.trim()) throw new Error('prompt 不能为空')

        const { roles } = readRoles()
        const role = roles[roleId]
        const agentOptions = { provider: role.provider, model: role.model }
        if (role.reasoningEffort) agentOptions.reasoningEffort = role.reasoningEffort

        const request = {
          label: args.label || `${role.label}·${roleId}`,
          prompt: [{ type: 'text', text: prompt }],
          parent,
          agentOptions,
        }
        if (args.schema && typeof args.schema === 'object') request.outputSchema = args.schema

        const activation = await subagents.startActivation({
          provider: 'spawn',
          label: request.label,
          request,
          signal: exec.signal,
          delivery: 'parent',
        })

        const childId = activation && activation.childId ? String(activation.childId) : ''

        // 后台模式：立刻返回，跑完由运行时把结果作为通知投递回来。
        if (args && args.background === true) {
          Promise.resolve(activation.result)
            .catch(() => {})
            .finally(() => {
              try {
                activation.dispose && activation.dispose()
              } catch {}
            })
          return {
            role: roleId,
            stopReason: 'started',
            text: '',
            background: true,
            subagentId: childId,
            route: {
              provider: role.provider,
              model: role.model,
              reasoningEffort: role.reasoningEffort || 'default',
            },
          }
        }

        let result
        try {
          result = await activation.result
        } finally {
          try {
            await activation.dispose()
          } catch {}
        }

        // 工具返回值必须是无损 JSON：不能带 undefined 字段。
        const value = {
          role: roleId,
          stopReason: String(result && result.stopReason || 'unknown'),
          text: textOf(result && result.output),
          route: {
            provider: role.provider,
            model: role.model,
            reasoningEffort: role.reasoningEffort || 'default',
          },
        }
        const structured = result && result.structured
        if (structured && typeof structured === 'object') value.structured = structured
        if (result && result.diagnostic) value.diagnostic = String(result.diagnostic)
        if (childId) value.subagentId = childId
        return value
      },
    }),
  )
}
