// LifeOS frontend entry
import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import App from './App.jsx'
import Login from './pages/Login.jsx'
import Records from './pages/Records.jsx'
import Timeline from './pages/Timeline.jsx'
import Knowledge from './pages/Knowledge.jsx'
import Goals from './pages/Goals.jsx'
import Board from './pages/Board.jsx'
import Today from './pages/Today.jsx'
import Projections from './pages/Projections.jsx'
import Stats from './pages/Stats.jsx'
import Users from './pages/Users.jsx'
import Settings from './pages/Settings.jsx'
import './styles.css'

const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    path: '/',
    element: <App />,
    children: [
      { index: true, element: <Today /> },
      { path: 'records', element: <Records /> },
      { path: 'timeline', element: <Timeline /> },
      { path: 'knowledge', element: <Knowledge /> },
      { path: 'goals', element: <Goals /> },
      { path: 'board', element: <Board /> },
      { path: 'projections', element: <Projections /> },
      { path: 'stats', element: <Stats /> },
      { path: 'settings', element: <Settings /> },
      { path: 'users', element: <Users /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')).render(<RouterProvider router={router} />)
