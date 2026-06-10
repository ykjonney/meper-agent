/**
 * App Layout — clean white sidebar + header + content.
 */
import { Outlet } from 'react-router-dom'
import Sidebar from './sidebar'
import Header from './header'

export default function AppLayout() {
  return (
    <div className="min-h-screen bg-white flex">
      <Sidebar />

      <div className="flex-1 flex flex-col min-w-0">
        <Header />
        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export { AppLayout }
