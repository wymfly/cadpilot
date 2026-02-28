import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './contexts/ThemeContext.tsx';
import WorkbenchLayout from './layouts/WorkbenchLayout.tsx';
import MainLayout from './layouts/MainLayout.tsx';
import { GenerateWorkflowProvider } from './contexts/GenerateWorkflowContext.tsx';
import { OrganicWorkflowProvider } from './contexts/OrganicWorkflowContext.tsx';
import PrecisionWorkbench from './pages/PrecisionWorkbench/index.tsx';
import OrganicWorkbench from './pages/OrganicWorkbench/index.tsx';
import Templates from './pages/Templates/index.tsx';
import Benchmark from './pages/Benchmark/index.tsx';
import RunBenchmark from './pages/Benchmark/RunBenchmark.tsx';
import ReportDetail from './pages/Benchmark/ReportDetail.tsx';
import Standards from './pages/Standards/index.tsx';
import Settings from './pages/Settings/index.tsx';
import LibraryPage from './pages/Library/index.tsx';
import PartDetail from './pages/Library/PartDetail.tsx';

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <GenerateWorkflowProvider>
          <OrganicWorkflowProvider>
            <Routes>
              {/* 新三栏工作台路由 */}
              <Route element={<WorkbenchLayout />}>
                <Route path="/" element={<Navigate to="/precision" replace />} />
                <Route path="/precision" element={<PrecisionWorkbench />} />
                <Route path="/organic" element={<OrganicWorkbench />} />
                <Route path="/library" element={<LibraryPage />} />
                <Route path="/library/:jobId" element={<PartDetail />} />
              </Route>

              {/* 保留旧路由兼容（重定向） */}
              <Route path="/generate" element={<Navigate to="/precision" replace />} />
              <Route path="/generate/organic" element={<Navigate to="/organic" replace />} />
              <Route path="/history" element={<Navigate to="/library" replace />} />
              <Route path="/history/:jobId" element={<Navigate to="/library/:jobId" replace />} />

              {/* 辅助页面使用旧布局 */}
              <Route element={<MainLayout />}>
                <Route path="/templates" element={<Templates />} />
                <Route path="/standards" element={<Standards />} />
                <Route path="/benchmark" element={<Benchmark />} />
                <Route path="/benchmark/run" element={<RunBenchmark />} />
                <Route path="/benchmark/:runId" element={<ReportDetail />} />
                <Route path="/settings" element={<Settings />} />
              </Route>
            </Routes>
          </OrganicWorkflowProvider>
        </GenerateWorkflowProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
