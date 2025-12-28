'use client';

import { useState, useEffect } from 'react';
import { adminApi } from '@/lib/adminApi';
import Link from 'next/link';
import NewsletterManager from './components/NewsletterManager';
import { LocalTime } from './components/LocalTime';
import Sidebar from './components/Sidebar';

export default function AdminDashboard() {
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [autoRefresh, setAutoRefresh] = useState(true);

  const AUTO_REFRESH_INTERVAL_SECONDS = parseInt(process.env.NEXT_PUBLIC_ADMIN_AUTO_REFRESH_SECONDS || '30', 10);

  useEffect(() => {
    const fetchStatus = async () => {
      try {
        const data = await adminApi.getStatus();
        setStatus(data);
      } catch (error) {
        console.error('Failed to fetch status:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchStatus();

    if (!autoRefresh) return;
    const interval = setInterval(fetchStatus, AUTO_REFRESH_INTERVAL_SECONDS * 1000);
    return () => clearInterval(interval);
  }, [autoRefresh, AUTO_REFRESH_INTERVAL_SECONDS]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
      <Sidebar />
      
      <div className="lg:ml-64 p-8 pb-20">
        <div className="max-w-6xl mx-auto">
          {/* Header */}
          <div className="flex items-center justify-between mb-8">
            <div>
              <h1 className="text-4xl font-bold text-white mb-2">Admin Dashboard</h1>
              <p className="text-gray-400">System status and controls</p>
            </div>
            <div className="flex items-center gap-4">
              <LocalTime date={new Date()} />
              <button
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`px-4 py-2 rounded-lg font-medium transition ${
                  autoRefresh 
                    ? 'bg-blue-500 hover:bg-blue-600 text-white' 
                    : 'bg-gray-700 hover:bg-gray-600 text-gray-100'
                }`}
              >
                {autoRefresh ? '⏸ Auto-refresh: ON' : '▶ Auto-refresh: OFF'}
              </button>
            </div>
          </div>

          {/* Main Content */}
          {loading ? (
            <div className="text-center py-20">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-white mx-auto mb-4"></div>
              <p className="text-gray-400">Loading system status...</p>
            </div>
          ) : status ? (
            <div className="space-y-6">
              {/* Status Overview */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="bg-card rounded-lg border border-border p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-muted-foreground">Health Status</p>
                      <p className="text-2xl font-bold text-white mt-2">
                        {status.is_healthy ? '✓ Healthy' : '⚠ Issues'}
                      </p>
                    </div>
                    <div className={`w-12 h-12 rounded-lg ${status.is_healthy ? 'bg-green-500/20' : 'bg-yellow-500/20'}`}>
                      {status.is_healthy ? '🟢' : '🟡'}
                    </div>
                  </div>
                </div>

                <div className="bg-card rounded-lg border border-border p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-muted-foreground">Pending Items</p>
                      <p className="text-2xl font-bold text-white mt-2">{status.total_pending || 0}</p>
                    </div>
                    <div className="w-12 h-12 rounded-lg bg-blue-500/20">📊</div>
                  </div>
                </div>

                <div className="bg-card rounded-lg border border-border p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-muted-foreground">In Progress</p>
                      <p className="text-2xl font-bold text-white mt-2">{status.total_in_progress || 0}</p>
                    </div>
                    <div className="w-12 h-12 rounded-lg bg-purple-500/20">⚙️</div>
                  </div>
                </div>

                <div className="bg-card rounded-lg border border-border p-6">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-muted-foreground">Auto-refresh Status</p>
                      <p className="text-sm font-mono text-white mt-2">
                        {autoRefresh ? '✓ Active' : '✗ Paused'}
                      </p>
                    </div>
                    <div className="w-12 h-12 rounded-lg bg-slate-500/20">🔄</div>
                  </div>
                </div>
              </div>

              {/* Navigation Links */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <Link href="/logs" className="group">
                  <div className="bg-card rounded-lg border border-border p-6 hover:border-blue-500 transition">
                    <h3 className="text-lg font-semibold text-white group-hover:text-blue-400 flex items-center gap-2">
                      📋 Activity Logs
                    </h3>
                    <p className="text-sm text-gray-400 mt-2">View system activity and events</p>
                  </div>
                </Link>

                <Link href="/sources" className="group">
                  <div className="bg-card rounded-lg border border-border p-6 hover:border-green-500 transition">
                    <h3 className="text-lg font-semibold text-white group-hover:text-green-400 flex items-center gap-2">
                      🔗 Data Sources
                    </h3>
                    <p className="text-sm text-gray-400 mt-2">Manage scraping sources</p>
                  </div>
                </Link>

                <Link href="/queue" className="group">
                  <div className="bg-card rounded-lg border border-border p-6 hover:border-purple-500 transition">
                    <h3 className="text-lg font-semibold text-white group-hover:text-purple-400 flex items-center gap-2">
                      📦 Processing Queue
                    </h3>
                    <p className="text-sm text-gray-400 mt-2">Monitor job queues</p>
                  </div>
                </Link>
              </div>

              {/* Newsletter Manager */}
              <NewsletterManager />
            </div>
          ) : (
            <div className="text-center py-20 text-red-500">
              Failed to load dashboard data
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
