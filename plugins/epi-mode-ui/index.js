import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const name = 'epi-mode'
export const inject = ['webServer']

// 技能目录解析：宁可多找几个位置，也不要因为搬家把配置写丢。
// 顺序：显式环境变量 → 预设专属目录 → 旧的全全局技能目录（兼容期）。
const CANDIDATES = [
  process.env.EPI_MODE_SKILL_DIR,
  path.join(os.homedir(), '.dsh', 'epi-mode', 'skills', 'epi-research-mode'),
  path.join(os.homedir(), '.agents', 'skills', 'epi-research-mode'),
].filter((value) => typeof value === 'string' && value.length > 0)

function resolveSkillDir() {
  for (const candidate of CANDIDATES) {
    try {
      if (fs.existsSync(path.join(candidate, 'SKILL.md'))) return candidate
    } catch {}
  }
  return CANDIDATES[1]
}

const skillDir = () => resolveSkillDir()
const rolesFile = () => path.join(skillDir(), 'config', 'roles.json')
const promptFile = (id) => path.join(skillDir(), 'roles', `${id}.md`)

const ROLE_IDS = ['executor', 'plotter', 'reviewer']

const DEFAULT_ROLES = {
  executor: {
    label: '执行者',
    hint: '写码、跑数、出表。禁止解读结果。',
    provider: 'deepseek-account',
    model: 'deepseek-flash',
    concurrencyMax: 3,
  },
  plotter: {
    label: '画图者',
    hint: '按科研规范作图。禁止改动数值。',
    provider: 'deepseek-account',
    model: 'deepseek-flash',
    concurrencyMax: 2,
  },
  reviewer: {
    label: '审稿人',
    hint: '独立审稿，出四档结论。禁止改文件。',
    provider: 'deepseek-account',
    model: 'deepseek-flash',
    concurrencyMax: 1,
  },
}

function readRoles() {
  const file = rolesFile()
  let stored = {}
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (parsed && typeof parsed === 'object' && parsed.roles && typeof parsed.roles === 'object') {
      stored = parsed.roles
    }
  } catch {}
  const roles = {}
  for (const id of ROLE_IDS) {
    const base = DEFAULT_ROLES[id]
    const row = stored[id] && typeof stored[id] === 'object' ? stored[id] : {}
    roles[id] = {
      id,
      label: typeof row.label === 'string' && row.label ? row.label : base.label,
      hint: base.hint,
      provider: typeof row.provider === 'string' && row.provider ? row.provider : base.provider,
      model: typeof row.model === 'string' && row.model ? row.model : base.model,
      concurrencyMax: Number.isFinite(row.concurrencyMax) ? row.concurrencyMax : base.concurrencyMax,
    }
  }
  return { file, exists: fs.existsSync(file), roles }
}

function readPrompts() {
  const prompts = {}
  for (const id of ROLE_IDS) {
    const file = promptFile(id)
    try {
      prompts[id] = { file, exists: true, text: fs.readFileSync(file, 'utf8') }
    } catch {
      prompts[id] = { file, exists: false, text: '' }
    }
  }
  return prompts
}

function safeText(value, max) {
  return typeof value === 'string' ? value.slice(0, max) : undefined
}

function saveState(payload) {
  const written = []
  if (payload.roles && typeof payload.roles === 'object') {
    const current = readRoles()
    for (const id of ROLE_IDS) {
      const row = payload.roles[id]
      if (!row || typeof row !== 'object') continue
      const provider = safeText(row.provider, 120)
      const model = safeText(row.model, 160)
      if (provider) current.roles[id].provider = provider
      if (model) current.roles[id].model = model
    }
    const file = rolesFile()
    fs.mkdirSync(path.dirname(file), { recursive: true })
    const body = {
      version: 1,
      updatedAt: new Date().toISOString(),
      note: '由「设置 → 科研模式」写入。主 agent 派发前读本文件决定每个角色用哪个模型。',
      defaults: { onFailure: 'inherit', concurrencyMax: 4 },
      roles: current.roles,
    }
    fs.writeFileSync(file, `${JSON.stringify(body, null, 2)}\n`, 'utf8')
    written.push(file)
  }
  if (payload.prompts && typeof payload.prompts === 'object') {
    for (const id of ROLE_IDS) {
      const text = payload.prompts[id]
      if (typeof text !== 'string') continue
      const file = promptFile(id)
      fs.mkdirSync(path.dirname(file), { recursive: true })
      fs.writeFileSync(file, text, 'utf8')
      written.push(file)
    }
  }
  return written
}

async function catalogOf(ctx) {
  const llm = ctx.get('llm')
  if (!llm || typeof llm.listProviders !== 'function') return { providers: [], error: 'llm service unavailable' }
  let providers = []
  try {
    providers = await llm.listProviders()
  } catch (error) {
    return { providers: [], error: String(error && error.message ? error.message : error) }
  }
  const out = []
  for (const provider of providers) {
    const row = { provider: provider.id, name: provider.name || provider.id, models: [] }
    try {
      const models = await llm.listModels(provider.id)
      row.models = models.map((model) => ({ id: model.id, name: model.name || model.id }))
    } catch (error) {
      row.error = String(error && error.message ? error.message : error)
    }
    out.push(row)
  }
  return { providers: out }
}

function sendJson(res, status, value) {
  const body = JSON.stringify(value)
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(body),
  })
  res.end(body)
}

function readBody(req, limit = 1 << 20) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let size = 0
    req.on('data', (chunk) => {
      size += chunk.length
      if (size > limit) {
        reject(new Error('payload too large'))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

async function handleState(ctx, req, res) {
  try {
    if (req.method === 'GET') {
      const roles = readRoles()
      const catalog = await catalogOf(ctx)
      sendJson(res, 200, {
        skillDir: skillDir(),
        rolesFile: roles.file,
        rolesFileExists: roles.exists,
        roles: ROLE_IDS.map((id) => roles.roles[id]),
        prompts: readPrompts(),
        catalog,
      })
      return
    }
    if (req.method === 'POST') {
      const raw = await readBody(req)
      let payload = {}
      try {
        payload = JSON.parse(raw || '{}')
      } catch {
        sendJson(res, 400, { ok: false, error: 'invalid JSON body' })
        return
      }
      sendJson(res, 200, { ok: true, written: saveState(payload) })
      return
    }
    sendJson(res, 405, { ok: false, error: 'method not allowed' })
  } catch (error) {
    sendJson(res, 500, { ok: false, error: String(error && error.message ? error.message : error) })
  }
}

export function apply(ctx) {
  ctx.effect(() =>
    ctx.webServer.register({
      kind: 'exact',
      path: '/epi-mode/state',
      handler: (req, res) => handleState(ctx, req, res),
    }),
  )
  ctx.effect(() =>
    ctx.webServer.register({
      kind: 'exact',
      path: '/epi-mode/health',
      handler: (req, res) =>
        sendJson(res, 200, {
          ok: true,
          skillDir: skillDir(),
          candidates: CANDIDATES,
          rolesFile: rolesFile(),
        }),
    }),
  )
}
