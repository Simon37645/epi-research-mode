export const name = 'epi-guard'

// 顺序敏感：越具体的放前面，命中即拒绝。
const RULES = [
  { id: 'rm-recursive-force', re: /\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+.*|.*-[a-zA-Z]*[rR][a-zA-Z]*)/, why: 'rm 递归删除' },
  { id: 'rm-force', re: /\brm\s+(-[a-zA-Z]*f|--force)\b/, why: 'rm 强制删除' },
  { id: 'remove-item', re: /\b(?:Remove-Item|Remove-ItemProperty|Clear-Content)\b/i, why: 'PowerShell 删除/清空' },
  { id: 'del-switch', re: /\b(?:del|erase)\s+[^\n]*\/[sq]\b/i, why: 'del 带 /s 或 /q' },
  { id: 'rd-switch', re: /\b(?:rd|rmdir)\s+\/[sq]\b/i, why: 'rd /s 删目录树' },
  { id: 'git-clean', re: /\bgit\s+clean\s+-[a-zA-Z]*[fdx]/, why: 'git clean 删未跟踪文件' },
  { id: 'python-rmtree', re: /\bshutil\.rmtree\b/, why: 'shutil.rmtree' },
  { id: 'python-os-delete', re: /\bos\.(?:remove|unlink|rmdir)\s*\(/, why: 'os.remove / unlink / rmdir' },
  { id: 'python-path-unlink', re: /\.unlink\s*\(/, why: 'Path.unlink' },
  { id: 'find-delete', re: /\bfind\b[^\n]*\s-delete\b/, why: 'find -delete' },
  { id: 'sql-drop', re: /\bDROP\s+(?:TABLE|DATABASE|SCHEMA|VIEW)\b/i, why: 'SQL DROP' },
  { id: 'sql-truncate', re: /\bTRUNCATE\s+TABLE\b/i, why: 'SQL TRUNCATE' },
  { id: 'format-drive', re: /\bformat\s+[A-Za-z]:/i, why: '格式化磁盘' },
]

const TOOLS = new Set(['pwsh', 'bash', 'run_code', 'terminal'])

function commandText(args) {
  if (!args || typeof args !== 'object') return ''
  const parts = []
  for (const key of ['command', 'cmd', 'code', 'script', 'input']) {
    if (typeof args[key] === 'string') parts.push(args[key])
  }
  if (Array.isArray(args.argv)) parts.push(args.argv.join(' '))
  return parts.join('\n')
}

const DENY_TEMPLATE = (why, hit) =>
  `已拒绝：命中「${why}」（${hit}）。本模式要求**归档代替删除**，任何删除/清空命令都不允许。\n` +
  `改用：python <技能目录>/scripts/epi_run.py archive --dir <项目> --items "<相对路径>" --reason "<为什么归档>"\n` +
  `它会把文件移到 _archive/<时间戳>/ 并写 MANIFEST.json，可原路还原。确实必须删除时，请让用户手动执行。`

export function apply(ctx) {
  const tools = ctx.get('tools')
  if (!tools || typeof tools.guard !== 'function') return

  ctx.effect(() =>
    tools.guard((execution) => {
      try {
        if (!TOOLS.has(execution.name)) return undefined
        const text = commandText(execution.arguments)
        if (!text) return undefined
        for (const rule of RULES) {
          const match = rule.re.exec(text)
          if (match) return DENY_TEMPLATE(rule.why, match[0].slice(0, 60))
        }
      } catch {
        return undefined
      }
      return undefined
    }),
  )
}
