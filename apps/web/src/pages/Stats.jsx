import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api.js'

function Heatmap({ data }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!ref.current) return
    let chart
    import('echarts').then((echarts) => {
      chart = echarts.init(ref.current)
      const year = data.year
      const start = `${year}-01-01`
      const end = `${year}-12-31`
      const cell = Object.keys(data.actions).map((d) => [d, data.actions[d] || 0])
      chart.setOption({
        title: { text: `${year} 待办完成热力图`, left: 'center', textStyle: { fontSize: 14 } },
        tooltip: {},
        visualMap: { min: 0, max: 8, show: false, inRange: { color: ['#eef0f5', '#4f5df0'] } },
        calendar: {
          range: [start, end],
          cellSize: ['auto', 14],
          itemStyle: { color: '#fff', borderColor: '#e3e7f0' },
          yearLabel: { show: false },
        },
        series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: cell }],
      })
    })
    return () => chart?.dispose()
  }, [data])
  return <div ref={ref} className="chart" style={{ height: 200 }} />
}

function Trend({ trend }) {
  const ref = useRef(null)
  useEffect(() => {
    if (!ref.current || !trend?.series) return
    let chart
    import('echarts').then((echarts) => {
      chart = echarts.init(ref.current)
      const s = trend.series
      chart.setOption({
        title: { text: '近 30 天待办完成情况', left: 'center', textStyle: { fontSize: 14 } },
        tooltip: { trigger: 'axis' },
        legend: { data: ['完成', '计划'], top: 24 },
        grid: { top: 60, left: 40, right: 20, bottom: 30 },
        xAxis: { type: 'category', data: s.map((x) => x.date.slice(5)) },
        yAxis: { type: 'value', minInterval: 1 },
        series: [
          { name: '完成', type: 'bar', data: s.map((x) => x.done), itemStyle: { color: '#4f5df0' } },
          { name: '计划', type: 'line', data: s.map((x) => x.planned), smooth: true, itemStyle: { color: '#b9c0d4' } },
        ],
      })
    })
    return () => chart?.dispose()
  }, [trend])
  const sum = trend?.summary
  return (
    <>
      {sum && (
        <div className="row" style={{ justifyContent: 'center', marginBottom: 6 }}>
          <span className="badge green">完成 {sum.done}</span>
          <span className="badge gray">计划 {sum.planned}</span>
          <span className="badge">完成率 {sum.rate != null ? `${(sum.rate * 100).toFixed(0)}%` : '—'}</span>
        </div>
      )}
      <div ref={ref} className="chart" />
    </>
  )
}

export default function Stats() {
  const [heatmap, setHeatmap] = useState(null)
  const [trend, setTrend] = useState(null)
  const [proc, setProc] = useState(null)
  const [report, setReport] = useState('')

  useEffect(() => {
    api.get('/api/stats/heatmap').then(setHeatmap).catch(console.error)
    api.get('/api/stats/trend').then(setTrend).catch(console.error)
    api.get('/api/stats/procrastination').then(setProc).catch(console.error)
  }, [])

  const weekly = async () => {
    setReport('生成中…')
    const r = await api.get('/api/stats/weekly-report')
    setReport(r.report)
  }

  return (
    <div>
      <h2 className="page-title">📊 统计</h2>
      {heatmap && <div className="card"><Heatmap data={heatmap} /></div>}
      <div className="card">{trend && <Trend trend={trend} />}</div>
      {proc && (
        <div className="card row">
          <span className="badge red">欠账 {proc.debt}</span>
          <span className="badge gray">已放弃 {proc.given_up}</span>
          <span className="badge">平均顺延 {proc.avg_postpone_count} 次</span>
        </div>
      )}
      <div className="card">
        <div className="spread">
          <b>周报</b>
          <button className="ghost" onClick={weekly}>生成周报</button>
        </div>
        <p style={{ whiteSpace: 'pre-wrap' }}>{report || '点击生成本周总结'}</p>
      </div>
    </div>
  )
}
