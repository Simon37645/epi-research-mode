window.__ModuleLoader__.load({
  id: '@local/dsh-epi-mode',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const T = {
      text: 'var(--dsw-alias-label-primary)',
      dim: 'var(--dsw-alias-label-secondary)',
      bg: 'var(--dsw-alias-bg-layer-1)',
      bg2: 'var(--dsw-alias-bg-layer-2)',
      border: 'var(--dsw-alias-border-l1)',
      accent: 'var(--dsw-alias-brand-primary)',
      warn: 'var(--dsw-alias-state-warn-primary)',
      ok: 'var(--dsw-alias-state-success-primary)',
      err: 'var(--dsw-alias-state-error-primary)',
    }

    const EXAMPLE = '用流行病学统计科研模式分析 `data/cohort.csv`：研究问题是「长期 PM2.5 暴露是否与成人 log-CRP 水平独立相关」，结局 log_crp，暴露 pm25，协变量 age/sex/bmi/smoking，做 OLS 并给 95%CI。'

    function field(style) {
      return {
        width: '100%',
        boxSizing: 'border-box',
        background: T.bg2,
        color: T.text,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: '7px 10px',
        font: 'inherit',
        fontSize: 13,
        outline: 'none',
        ...style,
      }
    }

    function pill(text, color) {
      return h(
        'span',
        {
          style: {
            fontSize: 11,
            color,
            border: `1px solid ${color}`,
            borderRadius: 999,
            padding: '1px 8px',
            whiteSpace: 'nowrap',
          },
        },
        text,
      )
    }

    function step(index, title, body) {
      return h(
        'div',
        {
          key: title,
          style: {
            flex: 1,
            minWidth: 0,
            border: `1px solid ${T.border}`,
            borderRadius: 10,
            padding: '10px 12px',
            background: T.bg2,
          },
        },
        h(
          'div',
          { style: { display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 } },
          h(
            'span',
            {
              style: {
                width: 18,
                height: 18,
                borderRadius: 999,
                background: T.accent,
                color: '#fff',
                fontSize: 11,
                lineHeight: '18px',
                textAlign: 'center',
                flex: 'none',
              },
            },
            String(index),
          ),
          h('div', { style: { fontSize: 13, fontWeight: 600, color: T.text } }, title),
        ),
        h('div', { style: { fontSize: 12, color: T.dim, lineHeight: 1.7 } }, body),
      )
    }

    function modelOptions(catalog, provider, model) {
      const options = []
      let found = false
      for (const entry of catalog || []) {
        options.push(
          h(
            'optgroup',
            { key: entry.provider, label: entry.name || entry.provider },
            (entry.models || []).map((m) => {
              const value = `${entry.provider}|${m.id}`
              if (entry.provider === provider && m.id === model) found = true
              return h('option', { key: value, value }, `${m.name || m.id} — ${m.id}`)
            }),
          ),
        )
      }
      if (!found) {
        options.unshift(
          h('option', { key: '__current', value: `${provider}|${model}` }, `${model} — 未在目录中（未注册）`),
        )
      }
      return options
    }

    function roleCard(role, catalog, models, prompts, openPrompt, actions) {
      const current = models[role.id] || { provider: role.provider, model: role.model }
      const registered = (catalog || []).some(
        (entry) => entry.provider === current.provider && (entry.models || []).some((m) => m.id === current.model),
      )
      const prompt = prompts[role.id] || { text: '', file: '' }
      const expanded = openPrompt === role.id

      return h(
        'div',
        {
          key: role.id,
          style: {
            border: `1px solid ${T.border}`,
            background: T.bg,
            borderRadius: 12,
            padding: 14,
            marginBottom: 12,
          },
        },
        h(
          'div',
          { style: { display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 } },
          h('div', { style: { fontSize: 14, fontWeight: 600, color: T.text } }, role.label),
          h('div', { style: { fontSize: 12, color: T.dim, flex: 1 } }, role.hint || ''),
          registered ? pill('模型已注册', T.ok) : pill('未注册，会回退', T.warn),
        ),
        h(
          'div',
          { style: { display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12 } },
          h('div', { style: { fontSize: 12, color: T.dim, width: 64, flex: 'none' } }, '用哪个模型'),
          h(
            'select',
            {
              value: `${current.provider}|${current.model}`,
              onChange: (event) => actions.setModel(role.id, event.target.value),
              style: field({ flex: 1, cursor: 'pointer' }),
            },
            modelOptions(catalog, current.provider, current.model),
          ),
        ),
        h(
          'div',
          { style: { display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12 } },
          h('div', { style: { fontSize: 12, color: T.dim, width: 64, flex: 'none' } }, '推理强度'),
          h(
            'select',
            {
              value: current.reasoningEffort || '',
              onChange: (event) => actions.setEffort(role.id, event.target.value),
              style: field({ width: 180, flex: 'none', cursor: 'pointer' }),
            },
            h('option', { value: '' }, '跟随会话默认'),
            ...['low', 'medium', 'high', 'xhigh', 'max'].map((effort) =>
              h('option', { key: effort, value: effort }, effort)),
          ),
          h(
            'div',
            { style: { fontSize: 11, color: T.dim, flex: 1 } },
            current.reasoningEffort
              ? `该角色派发时用 ${current.reasoningEffort}`
              : '未指定时继承主 agent 当前档位',
          ),
        ),
        h(
          'div',
          { style: { display: 'flex', gap: 10, alignItems: 'center' } },
          h('div', { style: { fontSize: 12, color: T.dim, width: 64, flex: 'none' } }, '行为契约'),
          h(
            'button',
            {
              type: 'button',
              onClick: () => actions.togglePrompt(role.id),
              style: {
                background: 'transparent',
                border: `1px solid ${T.border}`,
                color: T.text,
                borderRadius: 8,
                padding: '5px 12px',
                fontSize: 12,
                cursor: 'pointer',
                flex: 'none',
              },
            },
            expanded ? '收起' : `查看/编辑（${prompt.text ? prompt.text.split('\n').length : 0} 行）`,
          ),
          h(
            'div',
            {
              style: {
                fontSize: 11,
                color: T.dim,
                flex: 1,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              },
            },
            '这个角色每次被派发时都要遵守的规则，通常不用改',
          ),
        ),
        expanded
          ? h(
              'div',
              { style: { marginTop: 10 } },
              h(
                'div',
                { style: { fontSize: 11, color: T.warn, marginBottom: 6, lineHeight: 1.6 } },
                '改动会影响该角色后续所有任务。这是行为契约（禁止什么、怎么返回、怎么停止），不是任务描述——具体任务由主 agent 在派发时给。',
              ),
              h('textarea', {
                value: prompt.text,
                onChange: (event) => actions.setPrompt(role.id, event.target.value),
                spellCheck: false,
                style: field({
                  minHeight: 240,
                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
                  fontSize: 12,
                  lineHeight: 1.5,
                  resize: 'vertical',
                }),
              }),
              h('div', { style: { fontSize: 11, color: T.dim, marginTop: 6 } }, prompt.file || ''),
            )
          : null,
      )
    }

    function EpimodePage() {
      const [data, setData] = React.useState(null)
      const [error, setError] = React.useState('')
      const [models, setModels] = React.useState({})
      const [prompts, setPrompts] = React.useState({})
      const [openPrompt, setOpenPrompt] = React.useState(null)
      const [openGuide, setOpenGuide] = React.useState(true)
      const [message, setMessage] = React.useState('')
      const [copied, setCopied] = React.useState(false)
      const [saving, setSaving] = React.useState(false)

      async function load() {
        setError('')
        try {
          const response = await fetch('/epi-mode/state', { headers: { accept: 'application/json' } })
          if (!response.ok) throw new Error(`HTTP ${response.status}`)
          const payload = await response.json()
          setData(payload)
          const nextModels = {}
          for (const role of payload.roles) {
            nextModels[role.id] = {
              provider: role.provider,
              model: role.model,
              reasoningEffort: role.reasoningEffort || '',
            }
          }
          setModels(nextModels)
          setPrompts(payload.prompts || {})
        } catch (cause) {
          setError(String(cause && cause.message ? cause.message : cause))
        }
      }

      React.useEffect(() => {
        void load()
      }, [])

      const actions = {
        setModel(roleId, value) {
          const [provider, model] = value.split('|')
          setModels((prev) => ({ ...prev, [roleId]: { ...(prev[roleId] || {}), provider, model } }))
          setMessage('')
        },
        setEffort(roleId, value) {
          setModels((prev) => ({ ...prev, [roleId]: { ...(prev[roleId] || {}), reasoningEffort: value } }))
          setMessage('')
        },
        setPrompt(roleId, text) {
          setPrompts((prev) => ({ ...prev, [roleId]: { ...(prev[roleId] || {}), text } }))
          setMessage('')
        },
        togglePrompt(roleId) {
          setOpenPrompt((prev) => (prev === roleId ? null : roleId))
        },
      }

      async function save() {
        setSaving(true)
        setMessage('')
        try {
          const body = {
            roles: Object.fromEntries(
              Object.entries(models).map(([id, value]) => [id, {
                provider: value.provider,
                model: value.model,
                reasoningEffort: value.reasoningEffort || '',
              }]),
            ),
            prompts: Object.fromEntries(Object.entries(prompts).map(([id, value]) => [id, value.text])),
          }
          const response = await fetch('/epi-mode/state', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(body),
          })
          const payload = await response.json()
          if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`)
          setMessage('已保存。回到对话发起任务，就会按新的路由派发。')
        } catch (cause) {
          setMessage(`保存失败：${cause && cause.message ? cause.message : cause}`)
        } finally {
          setSaving(false)
        }
      }

      async function copyExample() {
        try {
          await navigator.clipboard.writeText(EXAMPLE)
          setCopied(true)
          setTimeout(() => setCopied(false), 2000)
        } catch {
          setCopied(false)
          setMessage('复制失败，请手动选中示例句。')
        }
      }

      if (error) {
        return h(
          'div',
          { style: { padding: 20, color: T.text, fontSize: 13 } },
          h('div', { style: { color: T.err, marginBottom: 8 } }, `读取失败：${error}`),
          h('button', { type: 'button', onClick: () => void load(), style: field({ width: 120, cursor: 'pointer' }) }, '重试'),
        )
      }

      if (!data) {
        return h('div', { style: { padding: 20, color: T.dim, fontSize: 13 } }, '读取中…')
      }

      const catalog = data.catalog && data.catalog.providers
      const active = data.roles
        .map((role) => {
          const current = models[role.id] || { model: role.model }
          return `${role.label} ${current.model}`
        })
        .join(' · ')

      return h(
        'div',
        { style: { padding: '4px 2px 28px', fontSize: 13, color: T.text } },
        h(
          'div',
          { style: { marginBottom: 14 } },
          h('div', { style: { fontSize: 15, fontWeight: 600, marginBottom: 6 } }, '流行病学统计科研模式'),
          h(
            'div',
            { style: { fontSize: 12, color: T.dim, lineHeight: 1.7 } },
            '主 agent 出方案、派活、验收；执行者写码跑数；画图者作图；审稿人独立审。每轮产生一个新版本号，历史版本全部留档。',
          ),
        ),

        h(
          'div',
          {
            style: {
              border: `1px solid ${T.border}`,
              borderRadius: 12,
              padding: 12,
              marginBottom: 14,
              background: T.bg2,
            },
          },
          h(
            'div',
            {
              style: {
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                cursor: 'pointer',
                marginBottom: openGuide ? 12 : 0,
              },
              onClick: () => setOpenGuide((prev) => !prev),
            },
            h('div', { style: { fontSize: 13, fontWeight: 600 } }, '怎么用'),
            h('div', { style: { fontSize: 12, color: T.dim, flex: 1 } }, '三步，不用记命令'),
            h('span', { style: { fontSize: 12, color: T.dim } }, openGuide ? '收起' : '展开'),
          ),
          openGuide
            ? h(
                'div',
                null,
                h(
                  'div',
                  { style: { display: 'flex', gap: 10, marginBottom: 12, alignItems: 'stretch' } },
                  step(1, '选模型', '下面三张卡各挑一个模型。不改就用默认的 V4.1-Flash。'),
                  step(2, '保存', '点保存，写回技能目录。只影响之后的派发，不会重跑历史。'),
                  step(3, '回对话发起', '把下面那句话贴进输入框，改成你的数据和研究问题。'),
                ),
                h(
                  'div',
                  {
                    style: {
                      border: `1px dashed ${T.border}`,
                      borderRadius: 10,
                      padding: '10px 12px',
                      background: T.bg,
                      marginBottom: 8,
                    },
                  },
                  h('div', { style: { fontSize: 11, color: T.dim, marginBottom: 6 } }, '发起时这样说'),
                  h('div', { style: { fontSize: 12, lineHeight: 1.8, color: T.text, userSelect: 'text' } }, EXAMPLE),
                ),
                h(
                  'div',
                  { style: { display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 } },
                  h(
                    'button',
                    {
                      type: 'button',
                      onClick: () => void copyExample(),
                      style: {
                        background: 'transparent',
                        border: `1px solid ${T.border}`,
                        color: T.text,
                        borderRadius: 8,
                        padding: '5px 12px',
                        fontSize: 12,
                        cursor: 'pointer',
                      },
                    },
                    copied ? '已复制' : '复制示例句',
                  ),
                  h(
                    'div',
                    { style: { fontSize: 11, color: T.dim } },
                    '技能会按关键词自动启用；也可以直接说「用流行病学统计科研模式」。',
                  ),
                ),
                h(
                  'div',
                  { style: { fontSize: 12, color: T.dim, lineHeight: 1.8 } },
                  '之后你会看到：主 agent 先写 v000 方案 → 派执行者跑数 → 派审稿人审 → 通过才交付。',
                  h('br'),
                  '每次派发都是一次「运行工作流」，在对话里能展开看每个成员的成败与用时。',
                ),
              )
            : null,
        ),

        ...data.roles.map((role) => roleCard(role, catalog, models, prompts, openPrompt, actions)),

        h(
          'div',
          { style: { display: 'flex', alignItems: 'center', gap: 12, marginTop: 4 } },
          h(
            'button',
            {
              type: 'button',
              disabled: saving,
              onClick: () => void save(),
              style: {
                background: T.accent,
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                padding: '8px 18px',
                fontSize: 13,
                fontWeight: 600,
                cursor: saving ? 'default' : 'pointer',
                opacity: saving ? 0.6 : 1,
              },
            },
            saving ? '保存中…' : '保存',
          ),
          h('button', { type: 'button', onClick: () => void load(), style: field({ width: 96, cursor: 'pointer' }) }, '重新读取'),
          h(
            'div',
            { style: { fontSize: 12, color: T.dim, flex: 1 } },
            message || '改完记得点保存，否则只留在页面上。',
          ),
        ),
        h(
          'div',
          { style: { marginTop: 16, fontSize: 11, color: T.dim, lineHeight: 1.8, borderTop: `1px solid ${T.border}`, paddingTop: 10 } },
          h('div', {}, `当前生效：${active}`),
          h('div', {}, `技能目录：${data.skillDir}`),
          h('div', {}, `路由文件：${data.rolesFile}${data.rolesFileExists ? '' : '（尚未生成，保存后创建）'}`),
          h('div', {}, '界面 v2'),
        ),
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('settings.section', () =>
          ctx.slots.register(
            { name: 'settings.section', id: 'epi-mode', order: 30, label: '科研模式' },
            EpimodePage,
          ),
        )
      },
    }
  },
})
