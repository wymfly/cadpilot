import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import MainLayout from './layouts/MainLayout.tsx';
import { GenerateWorkflowProvider } from './contexts/GenerateWorkflowContext.tsx';
import { OrganicWorkflowProvider } from './contexts/OrganicWorkflowContext.tsx';
import Home from './pages/Home/index.tsx';
import Generate from './pages/Generate/index.tsx';
import OrganicGenerate from './pages/OrganicGenerate/index.tsx';
import Templates from './pages/Templates/index.tsx';
import Benchmark from './pages/Benchmark/index.tsx';
import RunBenchmark from './pages/Benchmark/RunBenchmark.tsx';
import ReportDetail from './pages/Benchmark/ReportDetail.tsx';
import Standards from './pages/Standards/index.tsx';
import Settings from './pages/Settings/index.tsx';

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <GenerateWorkflowProvider>
          <OrganicWorkflowProvider>
            <Routes>
              <Route element={<MainLayout />}>
                <Route path="/" element={<Home />} />
                <Route path="/generate" element={<Generate />} />
                <Route path="/generate/organic" element={<OrganicGenerate />} />
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
    </ConfigProvider>
  );
}
