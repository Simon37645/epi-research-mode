window.__ModuleLoader__.load({
  id: '@local/dsh-epi-dispatch',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const T = {
      text: 'var(--dsw-alias-label-primary)',
      dim: 'var(--dsw-alias-label-secondary)',
      bg: 'var(--dsw-alias-bg-layer-2)',
      border: 'var(--dsw-alias-border-l1)',
      accent: 'var(--dsw-alias-brand-primary)',
      ok: 'var(--dsw-alias-state-success-primary)',
      warn: 'var(--dsw-alias-state-warn-primary)',
      err: 'var(--dsw-alias-state-error-primary)',
    }

    const ROLE_LABEL = { executor: '执行者', plotter: '画图者', reviewer: '审稿人' }

    // 结果块的形状由宿主决定，这里递归找我们自己的返回值（带 role + stopReason）。
    function findValue(node, depth) {
      if (!node || typeof node !== 'object' || depth > 6) return null
      if (typeof node.role === 'string' && typeof node.stopReason === 'string') return node
      for (const key of ['value', 'result', 'output', 'structured', 'content', 'meta', 'block', 'data']) {
        const found = findValue(node[key], depth + 1)
        if (found) return found
      }
      if (Array.isArray(node)) {
        for (const item of node) {
          const found = findValue(item, depth + 1)
          if (found) return found
        }
      }
      return null
    }

    function parseArgs(block) {
      const raw = block && (block.args ?? block.arguments)
      if (!raw) return {}
      if (typeof raw === 'object') return raw
      try {
        return JSON.parse(String(raw))
      } catch {
        return {}
      }
    }

    function chip(text, color) {
      return h(
        'span',
        {
          style: {
            fontSize: 11,
            lineHeight: '18px',
            padding: '0 8px',
            borderRadius: 999,
            color,
            border: `1px solid ${color}`,
            whiteSpace: 'nowrap',
          },
        },
        text,
      )
    }

    function EpimodeDispatchCard(props) {
      let args = {}
      let value = null
      try {
        args = parseArgs(props.block)
        value = findValue(props.block, 0)
      } catch {}

      const role = (value && value.role) || args.role || '?'
      const roleText = ROLE_LABEL[role] ? `${ROLE_LABEL[role]} · ${role}` : role
      const label = args.label || ''
      const background = Boolean((value && value.background) || args.background)
      const route = value && value.route ? value.route : null
      const stop = value ? String(value.stopReason || '') : ''

      let stateText = '进行中'
      let stateColor = T.warn
      if (props.phase === 'result' && value) {
        if (background) {
          stateText = '后台运行中'
          stateColor = T.accent
        } else if (stop === 'completed') {
          stateText = '完成'
          stateColor = T.ok
        } else if (stop) {
          stateText = stop
          stateColor = stop === 'aborted' || stop === 'error' ? T.err : T.warn
        }
      } else if (props.phase === 'preparing' || props.phase === 'start') {
        stateText = '派发中'
      }

      const routeText = route
        ? `${route.provider || '?'}/${route.model || '?'} @ ${route.reasoningEffort || '默认'}`
        : ''

      const preview = value
        ? (value.structured ? JSON.stringify(value.structured) : String(value.text || ''))
        : ''

      const subagentId = value && value.subagentId ? String(value.subagentId) : ''

      return h(
        'div',
        {
          style: {
            border: `1px solid ${T.border}`,
            background: T.bg,
            borderRadius: 10,
            padding: '9px 12px',
            margin: '2px 0',
            fontSize: 12,
            color: T.text,
          },
        },
        h(
          'div',
          { style: { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' } },
          chip(roleText, T.accent),
          routeText ? chip(routeText, T.dim) : null,
          chip(stateText, stateColor),
          label
            ? h('span', { style: { color: T.dim, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' } }, label)
            : null,
        ),
        subagentId
          ? h(
              'div',
              { style: { marginTop: 6, fontSize: 11, color: T.dim, fontFamily: 'ui-monospace, Consolas, monospace' } },
              `subagent ${subagentId}`,
            )
          : null,
        preview
          ? h(
              'div',
              {
                style: {
                  marginTop: 6,
                  fontSize: 11,
                  color: T.dim,
                  maxHeight: 44,
                  overflow: 'hidden',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                },
              },
              preview.length > 180 ? `${preview.slice(0, 180)}…` : preview,
            )
          : null,
      )
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('tool.call.toolview', () =>
          ctx.slots.register({ name: 'tool.call.toolview', key: 'epi_dispatch' }, EpimodeDispatchCard),
        )
      },
    }
  },
})
