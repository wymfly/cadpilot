import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ThemeProvider } from './contexts/ThemeContext.tsx';
import WorkbenchLayout, { FullWidthPage } from './layouts/WorkbenchLayout.tsx';
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
              {/* 所有页面统一使用 WorkbenchLayout */}
              <Route element={<WorkbenchLayout />}>
                <Route path="/" element={<Navigate to="/precision" replace />} />
                {/* 三栏工作台页面（自带左右面板） */}
                <Route path="/precision" element={<PrecisionWorkbench />} />
                <Route path="/organic" element={<OrganicWorkbench />} />
                <Route path="/library" element={<LibraryPage />} />
                <Route path="/library/:jobId" element={<PartDetail />} />
                {/* 全宽页面（无左右面板） */}
                <Route path="/templates" element={<FullWidthPage><Templates /></FullWidthPage>} />
                <Route path="/standards" element={<FullWidthPage><Standards /></FullWidthPage>} />
                <Route path="/benchmark" element={<FullWidthPage><Benchmark /></FullWidthPage>} />
                <Route path="/benchmark/run" element={<FullWidthPage><RunBenchmark /></FullWidthPage>} />
                <Route path="/benchmark/:runId" element={<FullWidthPage><ReportDetail /></FullWidthPage>} />
                <Route path="/settings" element={<FullWidthPage><Settings /></FullWidthPage>} />
              </Route>

              {/* 保留旧路由兼容（重定向） */}
              <Route path="/generate" element={<Navigate to="/precision" replace />} />
              <Route path="/generate/organic" element={<Navigate to="/organic" replace />} />
              <Route path="/history" element={<Navigate to="/library" replace />} />
              <Route path="/history/:jobId" element={<Navigate to="/library/:jobId" replace />} />
            </Routes>
          </OrganicWorkflowProvider>
        </GenerateWorkflowProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
