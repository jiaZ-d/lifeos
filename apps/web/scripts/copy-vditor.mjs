// 把 vditor 的静态资源复制到 public/vditor/dist,配合初始化时的 cdn:'vditor'
// (vditor 按 {cdn}/dist/... 解析资源),本地化避免运行时依赖 unpkg CDN
import { cpSync, mkdirSync, rmSync } from 'node:fs'

rmSync('public/vditor', { recursive: true, force: true })
mkdirSync('public/vditor', { recursive: true })
cpSync('node_modules/vditor/dist', 'public/vditor/dist', { recursive: true })
console.log('vditor assets copied to public/vditor/dist')
